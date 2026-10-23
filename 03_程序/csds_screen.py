"""CSDS 售后对话初筛、固定交接点与人工复核。Python 3.10+，仅标准库。

关键词只用于初筛，程序不自动判定未决事项，也不使用 QA/摘要或后续结果。
"""

import argparse
from collections import Counter
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import platform
import random
import re
import shutil
import sys
import traceback


VERSION = "0.2-pilot"
PATH_VERSION = "20261023-project-relative-1"
TOPICS = {
    "退货退款": ["退货", "退款", "退钱", "退回", "返款", "退差价", "退掉"],
    "换货维修": ["换货", "维修", "返修", "保修", "质量问题", "坏了", "故障"],
    "物流异常": ["没收到", "没有收到", "未收到", "一直没到", "还没到", "还没发货", "没有发货", "物流不更新", "物流没更新", "物流异常", "丢件", "破损", "少件", "少收到", "少了一件", "漏发", "错发"],
    "费用权益": ["运费", "优惠券", "赔偿", "补偿", "退运费", "返还"],
}
PENDING_CUES = ["还没", "尚未", "未到账", "没到账", "没收到", "等待", "待审核", "审核中", "核实中", "处理中", "正在核实", "还在核实", "暂时无法", "暂时不能", "稍等", "稍后", "预计", "等待回复"]
PROCESS_CUES = ["已受理", "已经受理", "已提交", "已经提交", "帮您查询", "帮您核实", "为您查询", "为您核实", "联系商家", "联系专员", "反馈", "催促", "跟进", "申请"]
COMPLETION_CUES = ["已到账", "已经到账", "退款成功", "退货成功", "已解决", "已经解决", "处理完成", "无法退货", "不能退货", "不支持退货", "无法退款", "不能退款", "不支持退款", "不符合"]


def find_project_root():
    """从脚本位置向上找项目，和终端当前所在目录无关。"""
    code = Path(__file__).resolve()
    for parent in code.parents:
        if (parent / "01_研究说明" / "protocol_v0.2.md").is_file() and (parent / "02_数据").is_dir():
            return parent
    # 独立复制的历史代码可显式传入绝对路径，并使用旁边的规则快照。
    return code.parent


def project_path(value, base=None):
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else ((base or find_project_root()) / path).resolve()


def resolve_cli_paths(args):
    """CLI 的所有相对数据/输出路径统一从项目根目录计算。"""
    base = find_project_root()
    provided = {}
    legacy_changes = []
    for field in ("input", "output", "reviews", "run"):
        if hasattr(args, field):
            value = getattr(args, field)
            provided[field] = value
            if value:
                resolved = [str(project_path(p, base)) for p in value] if field == "input" else str(project_path(value, base))
                if field == "reviews":
                    old_path = Path(value)
                    if not old_path.is_absolute() and old_path.parts and old_path.parts[0].lower() == "work":
                        resolved = str(base / "05_人工标注" / Path(*old_path.parts[1:]))
                        legacy_changes.append({"field": field, "original": value, "resolved": resolved})
                setattr(args, field, resolved)
    if args.command in ("screen", "finalize") and not args.output:
        label = "筛选" if args.command == "screen" else "人工样本导出"
        stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S_%f")
        args.output = str(base / "04_实验记录" / f"{stamp}_{label}_v0.2")
    args.path_base = str(base)
    args.path_version = PATH_VERSION
    args.provided_paths = provided
    if legacy_changes:
        args.legacy_path_changes = legacy_changes
    if "COMPAT_ORIGINAL_ARGV" in globals():
        args.compat_original_argv = COMPAT_ORIGINAL_ARGV
        args.compat_path_changes = COMPAT_PATH_CHANGES
    return args


def compact(text):
    """仅匹配时去除 CSDS 的分词空格；导出仍保留原始 utterance。"""
    return re.sub(r"\s+", "", str(text)).lower()


def cue_hits(prefix, cues, speaker=None):
    hits = []
    for u in prefix:
        if speaker is not None and u["speaker"] != speaker:
            continue
        found = [c for c in cues if c in compact(u["utterance"])]
        if found:
            hits.append({"utterance_index": u["utterance_index"], "cues": found})
    return hits


def normalize_dialogue(record):
    turns = record.get("Dialogue")
    if not isinstance(turns, list) or not turns:
        raise ValueError("Dialogue 必须是非空列表")
    normalized = []
    for i, u in enumerate(turns):
        if not isinstance(u, dict) or u.get("speaker") not in ("Q", "A"):
            raise ValueError("speaker 必须是 Q 或 A")
        if not isinstance(u.get("utterance"), str) or not u["utterance"].strip():
            raise ValueError("utterance 必须是非空字符串")
        normalized.append({"utterance_index": i, "turn": u.get("turn", i), "speaker": u["speaker"], "utterance": u["utterance"]})
    return normalized


def topic_hits(text):
    text = compact(text)
    return {name: [word for word in words if word in text] for name, words in TOPICS.items() if any(word in text for word in words)}


def select_prefix(record, agent_blocks=2, min_messages=4):
    """第一个含售后词的顾客发言后，第 k 个客服连续发言块结束时截断。

    k=2 是待预测试的设计约定，不是经验证的最优点。
    只通过总长度确认后面还有记录，不利用后文内容或既有摘要判断状态。
    """
    if agent_blocks < 1 or min_messages < 1:
        raise ValueError("agent_blocks 和 min_messages 必须为正整数")
    turns = normalize_dialogue(record)
    anchor = next((i for i, u in enumerate(turns) if u["speaker"] == "Q" and topic_hits(u["utterance"])), None)
    if anchor is None:
        return None, "no_customer_topic_hit"
    block_count = 0
    index = anchor + 1
    while index < len(turns):
        if turns[index]["speaker"] != "A":
            index += 1
            continue
        block_count += 1
        end = index
        while end + 1 < len(turns) and turns[end + 1]["speaker"] == "A":
            end += 1
        if block_count == agent_blocks:
            if end == len(turns) - 1:
                return None, "cut_at_dialogue_end"
            prefix = turns[:end + 1]
            if len(prefix) < min_messages:
                return None, "prefix_too_short"
            qtext = "\n".join(u["utterance"] for u in prefix if u["speaker"] == "Q")
            item = {
                "topic_anchor_index": anchor,
                "topic_hits": topic_hits(qtext),
                "cut_after_index": end,
                "prefix": prefix,
                "screening_signals": {
                    "pending_cues": cue_hits(prefix, PENDING_CUES),
                    "agent_process_cues": cue_hits(prefix, PROCESS_CUES, speaker="A"),
                    "completion_or_denial_cues": cue_hits(prefix, COMPLETION_CUES),
                },
            }
            return item, "candidate_needs_human_review"
        index = end + 1
    return None, "insufficient_agent_blocks"


def json_write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def jsonl_write(path, values):
    with path.open("w", encoding="utf-8") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False) + "\n")


def new_output_dir(value):
    path = Path(value).resolve()
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError(f"输出目录非空，为避免覆盖人工标注请使用新目录：{path}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def sha256_file(path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def now_local():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)
        return len(text)

    def flush(self):
        for stream in self.streams:
            stream.flush()


@contextmanager
def tracked_run(args, kind):
    """每次运行建新目录；失败也留痕，不覆盖旧运行或已有人工标注。"""
    out = new_output_dir(args.output)
    rules_dir = out / "rules"
    rules_dir.mkdir()
    (out / "logs").mkdir()
    params = {k: v for k, v in vars(args).items() if k != "func"}
    config = {
        "version": VERSION,
        "documentation_version": "20261023-structure-consistent-1",
        "path_version": PATH_VERSION,
        "kind": kind,
        "parameters": params,
        "topic_keywords": TOPICS,
        "pending_cues": PENDING_CUES,
        "process_cues": PROCESS_CUES,
        "completion_or_denial_cues": COMPLETION_CUES,
        "cue_usage": "仅候选提示；不据此确定未决事项，也不优先抽取线索较强的样本。",
        "eligibility": "固定截断前至少1项人工确认为 open、具有原文证据和明确完成终点的事项。",
        "input_to_summarizer": "仅模型输入文件中的 dialogue；不得加入 gold、QA、现成摘要或后续对话。",
    }
    json_write(rules_dir / "rules.json", config)
    code = Path(__file__).resolve()
    shutil.copy2(code, rules_dir / "csds_screen.py")
    for name in ("test_csds_screen.py", "readable_records.py"):
        other = code.parent / name
        if other.is_file():
            shutil.copy2(other, rules_dir / name)
    launcher = find_project_root() / "运行项目.ps1"
    if launcher.is_file():
        shutil.copy2(launcher, rules_dir / "运行项目.ps1")
    compat = find_project_root() / "csds_screen.py"
    if compat.is_file() and compat.resolve() != code:
        shutil.copy2(compat, rules_dir / "旧命令入口.py")
    protocol = next((p for p in (
        code.parent / "protocol_v0.2.md",
        code.parent / "rules" / "protocol_v0.2.md",
        find_project_root() / "01_研究说明" / "protocol_v0.2.md",
    ) if p.is_file()), find_project_root() / "01_研究说明" / "protocol_v0.2.md")
    if not protocol.is_file():
        raise ValueError(f"缺少规则说明文件：{protocol}；请保留项目目录结构")
    shutil.copy2(protocol, rules_dir / "rule_explanation.md")
    # 将协议放在代码快照的相对查找位置，旧运行可独立复现。
    shutil.copy2(protocol, rules_dir / "protocol_v0.2.md")
    record = {
        "record_type": "recorded_at_execution",
        "version": VERSION,
        "kind": kind,
        "status": "running",
        "started_at": now_local(),
        "time_zone": "UTC+08:00",
        "ended_at": None,
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "working_directory": str(Path.cwd()),
        "invocation_argv": [sys.executable, *sys.argv],
        "parameters": params,
        "code_sha256": sha256_file(code),
        "inputs": [],
    }
    record_path = out / "run_record.json"
    json_write(record_path, record)
    console = out / "logs" / "console.log"
    with console.open("w", encoding="utf-8") as logfile:
        with redirect_stdout(Tee(sys.stdout, logfile)):
            try:
                input_paths = args.input if kind == "screen" else [args.reviews]
                for value in input_paths:
                    source = Path(value).resolve()
                    record["inputs"].append({"path": str(source), "sha256": sha256_file(source), "bytes": source.stat().st_size})
                if kind == "finalize":
                    (out / "inputs").mkdir()
                    shutil.copy2(Path(args.reviews), out / "inputs" / "human_reviews.json")
                json_write(record_path, record)
                yield out
                for source in record["inputs"]:
                    if sha256_file(Path(source["path"])) != source["sha256"]:
                        raise ValueError("运行期间输入文件发生变化，本次运行标记失败")
                record["status"] = "completed"
            except BaseException as error:
                record["status"] = "failed"
                record["error"] = f"{type(error).__name__}: {error}"
                logfile.write(traceback.format_exc())
                raise
            finally:
                logfile.flush()
                record["ended_at"] = now_local()
                from readable_records import write_run_summary
                write_run_summary(out, record)
                json_write(record_path, record)
                if out.parent == find_project_root() / "04_实验记录":
                    try:
                        from readable_records import refresh_project_indexes
                        refresh_project_indexes(find_project_root())
                    except (OSError, ValueError, TypeError) as error:
                        record["documentation_refresh_error"] = str(error)
                record["files"] = [{"path": p.relative_to(out).as_posix(), "bytes": p.stat().st_size, "sha256": sha256_file(p)} for p in sorted(out.rglob("*")) if p.is_file() and p != record_path]
                json_write(record_path, record)


def records_from_file(path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError(f"{path}: 需要 CSDS 官方格式的 JSON 列表")
    for i, record in enumerate(data):
        if not isinstance(record, dict):
            raise ValueError(f"{path}: 第 {i} 条记录不是对象")
        yield i, record


def blank_review(item):
    return {
        "review_id": item["record_key"],
        "dialogue_id": item["dialogue_id"],
        "cut_after_index": item["cut_after_index"],
        "prefix": item["prefix"],
        "review": {
            "cut_acceptable": None,
            "eligibility": "unreviewed",
            "reason": "",
            "reviewer": "",
            "items": [],
        },
    }


def review_markdown(reviews, title):
    from readable_records import review_markdown as render
    return render(reviews, title)


def _run_screen(args):
    paths = [Path(p).resolve() for p in args.input]
    if len(paths) != len(set(paths)):
        raise ValueError("重复传入同一个文件")
    if len({p.name for p in paths}) != len(paths):
        raise ValueError("输入文件名重复，请区分名称以保留来源")
    for path in paths:
        if not path.is_file():
            raise ValueError(f"找不到输入文件：{path}")
    out = Path(args.output).resolve()
    counts = Counter()
    candidates, exclusions = [], []
    audit_pool = []
    seen_ids, seen_text = set(), set()
    sources = []
    for path in paths:
        sources.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        for row_index, record in records_from_file(path):
            counts["input_records"] += 1
            did = str(record.get("DialogueID", ""))
            key = f"{path.name}:{did or 'row' + str(row_index)}"
            base = {"record_key": key, "dialogue_id": did, "source_file": path.name, "source_row": row_index}
            reason = None
            if record.get("QRole") != "用户":
                reason = "qrole_not_customer"
            else:
                counts["customer_records"] += 1
                try:
                    turns = normalize_dialogue(record)
                    # 全文哈希只用于去重，不用于抽取未决事项/截断/状态判定。
                    signature = hashlib.sha256(json.dumps([(u["speaker"], compact(u["utterance"])) for u in turns], ensure_ascii=False).encode("utf-8")).hexdigest()
                    if (did and did in seen_ids) or signature in seen_text:
                        reason = "duplicate_dialogue"
                    else:
                        if did:
                            seen_ids.add(did)
                        seen_text.add(signature)
                        item, reason = select_prefix(record, args.agent_blocks, args.min_messages)
                        if item is not None:
                            item.update(base)
                            candidates.append(item)
                        else:
                            # 审计样本仍只导出固定的前 N 条发言，不输出全程摘要/后续结果。
                            audit_pool.append({**base, "screen_exclusion_reason": reason, "audit_prefix": turns[:args.audit_prefix_messages]})
                except ValueError as error:
                    reason = "invalid_dialogue"
                    base["error"] = str(error)
            counts[reason] += 1
            if reason != "candidate_needs_human_review":
                exclusions.append({**base, "reason": reason})

    rng = random.Random(args.seed)
    candidates.sort(key=lambda x: x["record_key"])
    sample = rng.sample(candidates, min(args.sample, len(candidates)))
    # 分开的随机数生成器：改变主样本量不会改变审计样本。
    audit = random.Random(args.seed + 1).sample(audit_pool, min(args.audit_sample, len(audit_pool)))
    reviews = [blank_review(item) for item in sample]
    jsonl_write(out / "candidates.jsonl", candidates)
    jsonl_write(out / "exclusions.jsonl", exclusions)
    jsonl_write(out / "excluded_audit.jsonl", audit)
    json_write(out / "review_batch.json", reviews)
    (out / "review_batch.md").write_text(review_markdown(reviews, "这批对话先请人工看一遍"), encoding="utf-8")
    report = {
        "version": VERSION,
        "sources": sources,
        "rules": {"customer_only": True, "agent_blocks_after_first_topic_hit": args.agent_blocks, "min_prefix_messages": args.min_messages, "topic_keywords": TOPICS, "seed": args.seed},
        "counts": dict(counts),
        "review_sample_n": len(reviews),
        "excluded_audit_n": len(audit),
        "status": "关键词候选，不是人工确认的未决事项；不代表总体未决率。",
        "notes": ["未读 QA/UserSumm/AgentSumm/FinalSumm 进行筛选或状态判断。", "没有按 pending_cues 高低挑选样本；候选池等概率无放回抽样。", "提示词/摘要评测前请人工复核，原始摘要不作为交接时刻的标准答案。", "排除池审计只是检查规则可能漏筛的类型，不是总体召回率估计。", "输出可能仍包含原始个人信息，只在获授权的本地环境使用。"],
    }
    json_write(out / "screen_report.json", report)
    print(json.dumps({"output": str(out), "counts": dict(counts), "review_sample_n": len(reviews), "excluded_audit_n": len(audit)}, ensure_ascii=False, indent=2))


def _run_finalize(args):
    """仅接受人工确认的原定截止点，抽样并输出模型输入及独立 gold。"""
    source = Path(args.reviews)
    reviews = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(reviews, list):
        raise ValueError("复核文件必须是列表")
    accepted, seen = [], set()
    for record in reviews:
        rid = record["review_id"]
        if rid in seen:
            raise ValueError(f"重复 review_id: {rid}")
        seen.add(rid)
        review = record["review"]
        if review.get("eligibility") not in ("eligible", "ineligible", "uncertain", "unreviewed"):
            raise ValueError(f"{rid}: 非法 eligibility")
        if review.get("eligibility") != "eligible":
            continue
        if review.get("cut_acceptable") is not True:
            raise ValueError(f"{rid}: eligible 需要 cut_acceptable=true")
        if not str(review.get("reviewer", "")).strip():
            raise ValueError(f"{rid}: 请填写 reviewer")
        prefix = record["prefix"]
        if not isinstance(prefix, list) or not prefix:
            raise ValueError(f"{rid}: prefix 不能为空")
        indices = [u["utterance_index"] for u in prefix]
        if indices != list(range(len(prefix))) or record["cut_after_index"] != indices[-1]:
            raise ValueError(f"{rid}: prefix 必须从0连续到 cut_after_index")
        open_items, seen_items = [], set()
        for item in review.get("items", []):
            iid = item.get("item_id")
            if not isinstance(iid, str) or not iid or iid in seen_items:
                raise ValueError(f"{rid}: item_id 缺失或重复")
            seen_items.add(iid)
            if item.get("status") not in ("open", "resolved", "uncertain"):
                raise ValueError(f"{rid}: 非法事项状态")
            if item["status"] != "open":
                continue
            evidence = item.get("evidence_indices")
            if not isinstance(evidence, list) or not evidence or any(type(i) is not int or i not in indices for i in evidence):
                raise ValueError(f"{rid}: open 事项必须引用截断前的有效 evidence_indices")
            for field in ("request", "endpoint", "evidence_note"):
                if not isinstance(item.get(field), str) or not item[field].strip():
                    raise ValueError(f"{rid}: open 事项缺少 {field}")
            open_items.append(item)
        if not open_items:
            raise ValueError(f"{rid}: eligible 至少需要一项人工确认的 open 事项")
        accepted.append((record, open_items))
    if len(accepted) < args.n:
        raise ValueError(f"人工确认合格的只有 {len(accepted)} 段，少于要求的 {args.n} 段；请增加复核量，不会复制凑数。")
    accepted.sort(key=lambda x: x[0]["review_id"])
    picked = random.Random(args.seed).sample(accepted, args.n)
    inputs, gold = [], []
    for record, items in picked:
        # gold、关键词和人工判断不进入摘要模型输入，A/B 都使用同一个 input。
        inputs.append({"id": record["review_id"], "dialogue": [{"speaker": u["speaker"], "utterance": u["utterance"]} for u in record["prefix"]]})
        gold.append({"id": record["review_id"], "cut_after_index": record["cut_after_index"], "unresolved_items": items})
    out = Path(args.output).resolve()
    jsonl_write(out / "model_inputs.jsonl", inputs)
    jsonl_write(out / "gold_unresolved.jsonl", gold)
    json_write(out / "selection_report.json", {"review_file": str(source.resolve()), "review_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "accepted_n": len(accepted), "selected_n": len(picked), "seed": args.seed})
    print(f"已输出 {len(picked)} 段人工确认样本：{out}")


def run_screen(args):
    with tracked_run(args, "screen"):
        _run_screen(args)


def run_finalize(args):
    with tracked_run(args, "finalize"):
        _run_finalize(args)


def run_verify(args):
    root = Path(args.run).resolve()
    record_path = root / "run_record.json"
    record = json.loads(record_path.read_text(encoding="utf-8-sig"))
    expected = record.get("files", [])
    errors = []
    recorded_paths = set()
    for item in expected:
        relative = item["path"].replace("\\", "/")
        target = (root / relative).resolve()
        if not target.is_relative_to(root):
            raise ValueError("记录含有目录外路径")
        recorded_paths.add(relative)
        if not target.is_file() or sha256_file(target) != item["sha256"]:
            errors.append(relative)
    actual_paths = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and p != record_path}
    errors.extend(sorted(actual_paths - recorded_paths))
    if errors:
        raise ValueError("文件已变化、缺失或新增：" + ", ".join(errors))
    print(f"校验通过：{len(expected)} 个文件与运行记录一致；状态={record.get('status')}。校验不代表人工标签已通过语义审核。")


def positive_int(value):
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("必须是正整数")
    return n


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog="相对路径均从项目根目录计算，不受终端当前目录影响。")
    sub = parser.add_subparsers(dest="command", required=True)
    screen = sub.add_parser("screen", help="初筛、固定截断、随机抽取人工复核批次")
    screen.add_argument("--input", nargs="+", default=["02_数据/原始数据/train.json"], help="默认使用项目内的 train.json；相对路径从项目根目录计算")
    screen.add_argument("--output", help="省略时在04_实验记录中新建带时间的目录")
    screen.add_argument("--sample", type=positive_int, default=30)
    screen.add_argument("--seed", type=int, default=20261023)
    screen.add_argument("--agent-blocks", type=positive_int, default=2)
    screen.add_argument("--min-messages", type=positive_int, default=4)
    screen.add_argument("--audit-sample", type=positive_int, default=30)
    screen.add_argument("--audit-prefix-messages", type=positive_int, default=12)
    screen.set_defaults(func=run_screen)
    final = sub.add_parser("finalize", help="人工复核后抽取合格样本，分开输出模型输入与参考答案")
    final.add_argument("--reviews", default="05_人工标注/annotations_pilot_v0.2.json")
    final.add_argument("--output", help="省略时在04_实验记录中新建带时间的目录")
    final.add_argument("--n", type=positive_int, default=30)
    final.add_argument("--seed", type=int, default=20261023)
    final.set_defaults(func=run_finalize)
    verify = sub.add_parser("verify", help="只读检查归档文件是否发生变化")
    verify.add_argument("--run", required=True)
    verify.set_defaults(func=run_verify)
    args = parser.parse_args()
    try:
        resolve_cli_paths(args)
        args.func(args)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, f"错误：{error}\n")


if __name__ == "__main__":
    main()
