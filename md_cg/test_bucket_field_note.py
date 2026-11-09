# 判据：桶字段的语义自述会随读数给出（F13 口径修复）。
# 生效条件：调用 bucketnote.note(index["nodes"])。
# 正控：bucket 全等于自身 id 前缀 → form=id_family、note 说「不是 route_key 分区目录」
# 负控：bucket 是 orphan/cond_* 目录名 → form=bucket_dir、note 说「可按分区语义读」
# 负控：无 bucket 字段 → bucketed_nodes 0、form=bucket_dir（不冒充有分区）
from . import bucketnote


def main():
    ok = 0
    bad = []
    fam_nodes = {"mn_gw_%d" % i: {"bucket": "mn_gw"} for i in range(8)}
    fam_nodes.update({"gwmem_1": {"bucket": "gwmem"}})
    r = bucketnote.note(fam_nodes)
    if r["form"] == "id_family" and r["shares_id_family"] == 1.0 and "不是 route_key 分区目录" in r["note"]:
        ok += 1
    else:
        bad.append(("正控 id 族", r))
    dir_nodes = {"k1": {"bucket": "orphan"}, "k2": {"bucket": "cond_ab12"}, "k3": {"bucket": "orphan"}}
    r2 = bucketnote.note(dir_nodes)
    if r2["form"] == "bucket_dir" and "可按分区语义读" in r2["note"]:
        ok += 1
    else:
        bad.append(("负控 目录名", r2))
    r3 = bucketnote.note({"a": {}, "b": {"bucket": ""}})
    if r3["bucketed_nodes"] == 0 and r3["form"] == "bucket_dir" and r3["shares_id_family"] == 0.0:
        ok += 1
    else:
        bad.append(("负控 空桶", r3))
    print("通过 %d / %d" % (ok, 3))
    for b in bad:
        print("FAIL", b)
    print("RESULT", "PASS" if not bad else "FAIL")


if __name__ == "__main__":
    main()
