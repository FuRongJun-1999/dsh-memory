# -*- coding: utf-8 -*-
"""spatial_closure.py · 3D 时空视觉闭环 ④闭环编排 + 一致性自校验
感知点云 → 场景图（感知几何）→ 3D 渲染（语义几何）→ 对照自校验：
  中心对齐（投影中心）/ 深度关系（近远序）/ 尺寸一致（投影面积）
综合一致性分数 ≥0.8 → 闭环成立（零 LLM 确定性度量）。
"""
import sys
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')
try:
    from scene_graph import build_scene_graph
    from world3d_render import World3DCamera, render_scene
except ImportError:
    from .scene_graph import build_scene_graph
    from .world3d_render import World3DCamera, render_scene


def spatial_closure(pts, motion=None, camera=None, W=128, H=128):
    """闭环：感知 → 语义 → 渲染 → 自校验"""
    # ① 感知 → 场景图（感知几何）
    scene = build_scene_graph(pts, motion)
    # ③ 语义 → 3D 渲染（语义几何）
    cam = camera or World3DCamera()
    render = render_scene(scene, W=W, H=H, camera=cam)
    # ④ 对照自校验
    checks = {}
    objs = render["objects"]
    if len(objs) < 2:
        return {"ok": False, "reason": "物体不足（<2）无法对照", "scene": scene,
                "render": render, "consistency": 0.0, "checks": checks}
    # 4.1 中心对齐：物体世界质心 → 相机投影中心 vs 渲染 bbox 中心
    centers = []
    for o in scene["objects"]:
        uv, z, vis = cam.project([o["cx"], o["cy"], o["cz"]], W, H)
        centers.append((uv[0][0], uv[0][1]))
    center_errs = []
    for i, o in enumerate(objs):
        u_rend = (o["bbox"][0] + o["bbox"][2]) / 2.0
        v_rend = (o["bbox"][1] + o["bbox"][3]) / 2.0
        err = np.hypot(centers[i][0] - u_rend, centers[i][1] - v_rend) / np.hypot(W, H)
        center_errs.append(err)
    center_align = 1.0 - min(1.0, float(np.mean(center_errs)))
    checks["中心对齐"] = round(center_align, 3)

    # 4.2 深度关系：感知物体 z 序 vs 渲染深度序一致率
    scene_order = [o["cz"] for o in scene["objects"]]
    render_order = [o["z"] for o in objs]
    agree = sum(1 for a, b in zip(scene_order[:-1], scene_order[1:])
                for c, d in zip(render_order[:-1], render_order[1:])
                if (a <= b) == (c <= d))
    total = max(1, (len(scene_order) - 1) * (len(render_order) - 1))
    depth_rel = agree / total
    checks["深度关系"] = round(depth_rel, 3)

    # 4.3 尺寸一致：近物体投影面积应 > 远物体（相对差一致性）
    sizes = [(o["world_cz"], o["area"]) for o in objs]
    size_agree = sum(1 for i in range(len(sizes)) for j in range(len(sizes))
                     if i < j and (sizes[i][0] < sizes[j][0]) == (sizes[i][1] > sizes[j][1]))
    size_total = max(1, len(sizes) * (len(sizes) - 1) // 2)
    size_cons = size_agree / size_total
    checks["尺寸一致"] = round(size_cons, 3)

    consistency = round(0.4 * center_align + 0.3 * depth_rel + 0.3 * size_cons, 3)
    ok = consistency >= 0.8
    return {"ok": ok, "scene": scene, "render": render,
            "consistency": consistency, "checks": checks}


def closure_report(pts, motion=None, camera=None):
    """人类可读闭环报告"""
    r = spatial_closure(pts, motion, camera)
    print(f"① 感知点云: {len(pts)} 点 → 场景图 {r['scene']['count']} 物体")
    for o in r["scene"]["objects"]:
        m = o.get("motion", {})
        print(f"   [{o['id']}] {o['category']} (cx={o['cx']},cy={o['cy']},z={o['cz']}) "
              f"size={o['size']} 运动={m.get('direction', '-')}")
    print(f"② 3D 渲染: {len(r['render']['objects'])} 物体投影（近大远小）")
    for p in r["render"]["objects"]:
        print(f"   [{p['id']}] {p['category']} 投影面积={p['area']} 深度={p['z']}")
    print("③ 闭环自校验:")
    for k, v in r["checks"].items():
        print(f"   {k}: {v}")
    mark = "✔ 闭环成立" if r.get("ok") else "✘"
    print(f"\n=== 判定 ===\n一致性 = {r.get('consistency')} → {mark}（感知↔语义双向闭环，零 LLM）")
    return r


if __name__ == "__main__":
    print("=== 3D 时空视觉闭环：感知↔语义双向 + 自校验（零 LLM）===\n")
    from vision_3d import (synth_stereo_pair, stereo_disparity,
                           depth_from_disparity, pointcloud_from_depth)

    left, right = synth_stereo_pair()
    pts = pointcloud_from_depth(depth_from_disparity(stereo_disparity(left, right)), block=8)
    r = closure_report(pts, motion={"direction": "静止", "speed": 0, "is_static": True})
    sys.exit(0 if r.get("ok") else 1)
