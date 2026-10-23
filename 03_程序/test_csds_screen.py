"""验证研究流程的关键约束：无后文泄漏、按对话抽样、人工确认与 gold 隔离。"""
import argparse
from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
import shutil

import csds_screen as app

TEST_ROOT = Path(__file__).resolve().parent.parent / "99_临时文件" / "程序测试"
TEST_ROOT.mkdir(parents=True, exist_ok=True)


def fixture(did=1):
    lines = [("Q", "我 想 退 款"), ("A", "请提供订单号"), ("A", "还需要购买时间"),
             ("Q", "昨天买的，订单123"), ("A", "已经受理申请"), ("A", "仍在审核，尚未到账"),
             ("Q", "那我等通知"), ("A", "退款已经到账")]
    return {"DialogueID": did, "QRole": "用户", "Dialogue": [{"speaker": s, "turn": i, "utterance": t} for i, (s, t) in enumerate(lines)], "FinalSumm": ["后面退款成功"]}


def screen_args(source, out):
    return argparse.Namespace(input=[str(source)], output=str(out), agent_blocks=2, min_messages=4,
                              sample=2, audit_sample=2, audit_prefix_messages=12, seed=20261023)


class ResearchInvariants(unittest.TestCase):
    def test_completed_run_refreshes_index_in_a_portable_project_copy(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as folder:
            root = Path(folder)
            for name in ("01_研究说明", "02_数据/原始数据", "03_程序", "04_实验记录", "05_人工标注"):
                (root / name).mkdir(parents=True, exist_ok=True)
            for name in ("csds_screen.py", "readable_records.py"):
                shutil.copy2(Path(app.__file__).parent / name, root / "03_程序" / name)
            shutil.copy2(app.find_project_root() / "01_研究说明/protocol_v0.2.md", root / "01_研究说明/protocol_v0.2.md")
            app.json_write(root / "02_数据/原始数据/train.json", [fixture()])
            result = subprocess.run([sys.executable, str(root / "03_程序/csds_screen.py"), "screen", "--output", "04_实验记录/portable_run", "--sample", "1"], cwd=root / "03_程序", capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("已完成筛选1次", (root / "当前状态.md").read_text(encoding="utf-8"))
            self.assertIn("portable_run", (root / "04_实验记录/README.md").read_text(encoding="utf-8"))
            record = json.loads((root / "04_实验记录/portable_run/run_record.json").read_text(encoding="utf-8"))
            self.assertNotIn("documentation_refresh_error", record)

    def test_legacy_work_review_path_resolves_to_current_annotation_folder(self):
        args = argparse.Namespace(command="finalize", reviews="work/annotations_pilot_v0.2.json", output=None)
        app.resolve_cli_paths(args)
        self.assertEqual(Path(args.reviews), app.find_project_root() / "05_人工标注/annotations_pilot_v0.2.json")
        self.assertEqual(args.legacy_path_changes[0]["original"], "work/annotations_pilot_v0.2.json")

    def test_readable_summary_uses_actual_parameters(self):
        from readable_records import write_run_summary
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as folder:
            out = Path(folder)
            app.json_write(out / "screen_report.json", {"version":"pilot", "counts":{"input_records":1,"customer_records":1,"candidate_needs_human_review":1}, "rules":{"agent_blocks_after_first_topic_hit":3,"min_prefix_messages":7,"seed":9}, "review_sample_n":1,"excluded_audit_n":1})
            write_run_summary(out, {"kind":"screen","status":"completed","parameters":{"audit_prefix_messages":8}})
            text = (out / "实验记录.md").read_text(encoding="utf-8")
            self.assertIn("第3个客服", text)
            self.assertIn("至少保留7条", text)
            self.assertIn("前8句", text)

    def test_failed_export_explanation_points_to_current_folder(self):
        from readable_records import write_run_summary
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as folder:
            out = Path(folder)
            write_run_summary(out, {"kind":"finalize","status":"failed","error":"FileNotFoundError: work/annotations.json"})
            text = (out / "实验记录.md").read_text(encoding="utf-8")
            self.assertIn("状态：未完成", text)
            self.assertIn("当前工作文件放在05_人工标注", text)
            self.assertNotIn("状态：failed", text)

    def test_index_counts_success_failure_and_annotation_state(self):
        from readable_records import refresh_project_indexes
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as folder:
            root = Path(folder)
            (root / "04_实验记录/a").mkdir(parents=True)
            (root / "04_实验记录/b").mkdir()
            (root / "05_人工标注").mkdir()
            app.json_write(root / "04_实验记录/a/run_record.json", {"kind":"screen","status":"completed"})
            app.json_write(root / "04_实验记录/a/screen_report.json", {"counts":{"candidate_needs_human_review":3}})
            app.json_write(root / "04_实验记录/b/run_record.json", {"kind":"finalize","status":"failed"})
            app.json_write(root / "05_人工标注/annotations_pilot_v0.2.json", [{"review":{"eligibility":"unreviewed"}}])
            refresh_project_indexes(root)
            text = (root / "当前状态.md").read_text(encoding="utf-8")
            self.assertIn("已完成筛选1次", text)
            self.assertIn("失败运行1次", text)
            self.assertIn("尚未检查1段", text)

    def test_old_root_command_forwards_and_legacy_output_is_organized(self):
        project = app.find_project_root()
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as folder:
            source = Path(folder) / "train.json"
            app.json_write(source, [fixture()])
            # 临时输出父目录由 TemporaryDirectory 管理，范围固定在项目实验目录内。
            with tempfile.TemporaryDirectory(dir=project / "04_实验记录") as target_folder:
                target = Path(target_folder) / "run"
                old_output = str(Path("experiments") / Path(target_folder).name / "run")
                result = subprocess.run([sys.executable, str(project / "csds_screen.py"), "screen", "--input", str(source), "--output", old_output, "--sample", "1"], cwd=project, capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue((target / "review_batch.json").is_file())
                record = json.loads((target / "run_record.json").read_text(encoding="utf-8"))
                self.assertEqual(record["parameters"]["compat_path_changes"][0]["original"], old_output)
                self.assertEqual(record["parameters"]["compat_original_argv"][1], "screen")

    def test_default_paths_do_not_depend_on_current_directory(self):
        args = argparse.Namespace(command="screen", input=["02_数据/原始数据/train.json"], output=None)
        args = app.resolve_cli_paths(args)
        project = app.find_project_root()
        self.assertEqual(Path(args.input[0]), project / "02_数据/原始数据/train.json")
        self.assertEqual(Path(args.output).parent, project / "04_实验记录")
        self.assertEqual(Path(args.path_base), project)

    def test_real_cli_from_program_folder_and_unrelated_folder(self):
        project = app.find_project_root()
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as folder:
            root = Path(folder)
            source = root / "train.json"
            app.json_write(source, [fixture()])
            unrelated = root / "unrelated"
            unrelated.mkdir()
            for i, cwd in enumerate((project / "03_程序", unrelated)):
                output = root / f"out_{i}"
                command = [sys.executable, str(Path(app.__file__).resolve()), "screen", "--input", str(source.relative_to(project)), "--output", str(output.relative_to(project)), "--sample", "1"]
                result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue((output / "review_batch.json").is_file())
                record = json.loads((output / "run_record.json").read_text(encoding="utf-8"))
                self.assertEqual(record["inputs"][0]["path"], str(source))
                verify = subprocess.run([sys.executable, str(Path(app.__file__).resolve()), "verify", "--run", str(output.relative_to(project))], cwd=unrelated, capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)

    def test_finalize_cli_uses_project_relative_review_path(self):
        project = app.find_project_root()
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as folder:
            root = Path(folder)
            source = root / "reviews.json"
            app.json_write(source, [self.make_review()])
            output = root / "export"
            result = subprocess.run([sys.executable, str(Path(app.__file__).resolve()), "finalize", "--reviews", str(source.relative_to(project)), "--output", str(output.relative_to(project)), "--n", "1"], cwd=project / "03_程序", capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((output / "model_inputs.jsonl").is_file())

    def test_continuous_agent_messages_are_one_block(self):
        item, _ = app.select_prefix(fixture())
        self.assertEqual(item["cut_after_index"], 5)
        self.assertEqual([u["utterance_index"] for u in item["prefix"]], list(range(6)))

    def test_future_outcome_and_original_summaries_do_not_change_cut_or_signals(self):
        left = fixture()
        right = copy.deepcopy(left)
        right["Dialogue"][6]["utterance"] = "后续又增加维修和运费诉求"
        right["Dialogue"][7]["utterance"] = "退款彻底失败，消费者投诉"
        right["FinalSumm"] = ["完全不同的结果"]
        right["QA"] = [{"AnsSummLong": "未来才有的信息"}]
        self.assertEqual(app.select_prefix(left), app.select_prefix(right))

    def test_does_not_exclude_completed_cases_based_on_expected_effect(self):
        record = fixture()
        record["Dialogue"][5]["utterance"] = "退款已经到账，顾客确认收到"
        item, reason = app.select_prefix(record)
        self.assertIsNotNone(item)
        self.assertEqual(reason, "candidate_needs_human_review")
        self.assertTrue(item["screening_signals"]["completion_or_denial_cues"])
        self.assertEqual(app.blank_review(item | {"record_key": "test", "dialogue_id": "1"})["review"]["eligibility"], "unreviewed")

    def test_agent_keyword_cannot_substitute_for_customer_request(self):
        record = fixture()
        record["Dialogue"][0]["utterance"] = "你好"
        self.assertEqual(app.select_prefix(record)[1], "no_customer_topic_hit")

    def test_role_filter_reproducibility_and_no_input_mutation(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as folder:
            root = Path(folder)
            rows = [fixture(i) for i in range(5)]
            for i, record in enumerate(rows):
                record["Dialogue"][3]["utterance"] = f"昨天买的，订单{i}"
            rows[-1]["QRole"] = "商家"
            source = root / "train.json"
            app.json_write(source, rows)
            before = source.read_bytes()
            with redirect_stdout(io.StringIO()):
                app.run_screen(screen_args(source, root / "out1"))
                app.run_screen(screen_args(source, root / "out2"))
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual((root / "out1/review_batch.json").read_bytes(), (root / "out2/review_batch.json").read_bytes())
            report = json.loads((root / "out1/screen_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["counts"]["qrole_not_customer"], 1)
            self.assertEqual(report["counts"]["candidate_needs_human_review"], 4)
            with self.assertRaises(ValueError):
                app.run_screen(screen_args(source, root / "out1"))

    def make_review(self):
        item, _ = app.select_prefix(fixture())
        review = app.blank_review(item | {"record_key": "train.json:1", "dialogue_id": "1"})
        review["review"] = {"cut_acceptable": True, "eligibility": "eligible", "reviewer": "tester", "items": [
            {"item_id": "U1", "request": "退款到账", "endpoint": "实际收到退款", "status": "open", "evidence_indices": [0, 5], "evidence_note": "顾客申请退款，客服说仍在审核"}
        ]}
        return review

    def test_finalize_separates_gold_from_model_input(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as folder:
            root = Path(folder)
            source = root / "reviews.json"
            app.json_write(source, [self.make_review()])
            with redirect_stdout(io.StringIO()):
                app.run_finalize(argparse.Namespace(reviews=str(source), output=str(root / "final"), n=1, seed=1))
            model = json.loads((root / "final/model_inputs.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(set(model), {"id", "dialogue"})
            self.assertEqual(len(model["dialogue"]), 6)
            self.assertNotIn("unresolved_items", model)

    def test_finalize_rejects_future_evidence_and_unreviewed_cases(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as folder:
            root = Path(folder)
            source = root / "reviews.json"
            item = self.make_review()
            item["review"]["items"][0]["evidence_indices"] = [7]
            app.json_write(source, [item])
            args = argparse.Namespace(reviews=str(source), output=str(root / "final"), n=1, seed=1)
            with self.assertRaisesRegex(ValueError, "evidence_indices"):
                app.run_finalize(args)
            item["review"]["eligibility"] = "unreviewed"
            app.json_write(source, [item])
            args.output = str(root / "final_unreviewed")
            with self.assertRaisesRegex(ValueError, "少于要求"):
                app.run_finalize(args)

    def test_run_records_and_failed_run_are_preserved(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as folder:
            root = Path(folder)
            source = root / "train.json"
            app.json_write(source, [fixture()])
            with redirect_stdout(io.StringIO()):
                app.run_screen(screen_args(source, root / "screen"))
                app.run_verify(argparse.Namespace(run=str(root / "screen")))
            record = json.loads((root / "screen/run_record.json").read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "completed")
            self.assertTrue(record["started_at"].endswith("+08:00"))
            self.assertEqual(record["inputs"][0]["sha256"], app.sha256_file(source))
            self.assertTrue((root / "screen/rules/csds_screen.py").is_file())
            (root / "screen/review_batch.json").write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "已变化"):
                app.run_verify(argparse.Namespace(run=str(root / "screen")))
            bad_reviews = root / "bad.json"
            app.json_write(bad_reviews, [])
            with self.assertRaises(ValueError):
                app.run_finalize(argparse.Namespace(reviews=str(bad_reviews), output=str(root / "failed"), n=1, seed=1))
            failed = json.loads((root / "failed/run_record.json").read_text(encoding="utf-8"))
            self.assertEqual(failed["status"], "failed")
            self.assertTrue((root / "failed/logs/console.log").read_text(encoding="utf-8"))

    def test_exact_duplicates_are_not_counted_as_independent_dialogues(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as folder:
            root = Path(folder)
            source = root / "train.json"
            app.json_write(source, [fixture(1), fixture(2)])
            with redirect_stdout(io.StringIO()):
                app.run_screen(screen_args(source, root / "out"))
            report = json.loads((root / "out/screen_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["counts"]["duplicate_dialogue"], 1)


if __name__ == "__main__":
    unittest.main()
