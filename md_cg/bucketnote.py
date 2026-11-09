"""桶字段语义自述（2026-11-06 F13）。

生效条件：`MdCG.health()` 组装分桶健康度之后调用 `note(index["nodes"])`。
为什么要有：`routing.bucket_health` 拿 `index["buckets"]` 算「巨桶占比 / 期望扫描」，
但该库的 bucket 字段实测是**导入来源族名**（mn_gw / gwmem / gwtri / gwent / mn_doc），
不是 `route_key` 的分区目录名 —— 11,801 个节点里 9,320 个 bucket 恰等于自身 id 前缀，
2,459 个为空，orphan 只有 5，cond_* 为 0。于是「巨桶 36.4%」「路由无效 30.8%」测的是
同一 id 族内部的相对大小，与条件路由是否可用无关；磁盘上真正的分区是
`knowledge/orphan/<族>/`。

这与 provenance 把来源标签当悬空边（2026-11-05 修）是同一类错：**读数没说清它测的是
哪一套分区**。修法是让读数自己带上这一点，而不是改判据去迁就一个说不清的量。
"""


def note(nodes) -> dict:
    fam = 0
    tot = 0
    for nid, e in list((nodes or {}).items()):
        b = str((e or {}).get("bucket") or "")
        if not b:
            continue
        tot += 1
        if str(nid).startswith(b + "_"):
            fam += 1
    share = round(fam / tot, 4) if tot else 0.0
    family_form = bool(tot) and fam / tot >= 0.5
    return {
        "shares_id_family": share,
        "bucketed_nodes": tot,
        "form": "id_family" if family_form else "bucket_dir",
        "note": (
            "bucket 字段多数等于节点 id 前缀族（导入来源），不是 route_key 分区目录；"
            "巨桶/期望扫描因此测的是同族内部大小，与条件路由是否可用无关"
            if family_form else
            "bucket 字段与 route_key 分区目录形态一致，巨桶/期望扫描可按分区语义读"
        ),
    }
