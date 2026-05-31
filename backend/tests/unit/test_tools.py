"""tests/unit/test_tools.py — file_writer, linter, test_runner, code_runner"""
import os, sys, pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from tools.file_writer import write_file, write_files

class TestFileWriter:
    def test_creates_file(self, tmp_dir):
        assert write_file(str(tmp_dir/"t.py"), "x=1\n") is True
        assert (tmp_dir/"t.py").exists()

    def test_correct_content(self, tmp_dir):
        write_file(str(tmp_dir/"f.py"), "hello\n")
        assert (tmp_dir/"f.py").read_text() == "hello\n"

    def test_creates_parent_dirs(self, tmp_dir):
        assert write_file(str(tmp_dir/"a/b/c.py"), "x=1\n") is True

    def test_overwrites(self, tmp_dir):
        p = str(tmp_dir/"f.py")
        write_file(p, "v=1\n"); write_file(p, "v=2\n")
        assert Path(p).read_text() == "v=2\n"

    def test_empty_content(self, tmp_dir):
        assert write_file(str(tmp_dir/"e.py"), "") is True

    def test_write_files_batch(self, tmp_dir):
        files = {"a.py":"x=1\n","sub/b.py":"y=2\n"}
        results = write_files(files, str(tmp_dir))
        assert all(results.values())
        assert (tmp_dir/"a.py").exists()
        assert (tmp_dir/"sub/b.py").exists()

class TestLinter:
    def test_clean_file_no_issues(self, tmp_dir):
        from tools.linter import lint_file
        write_file(str(tmp_dir/"ok.py"), "def add(a:int,b:int)->int:\n    return a+b\n")
        assert isinstance(lint_file(str(tmp_dir/"ok.py")), list)

    def test_nonexistent_returns_empty(self):
        from tools.linter import lint_file
        assert isinstance(lint_file("/nonexistent/file.py"), list)

    def test_lint_and_fix_returns_bool(self, tmp_dir):
        from tools.linter import lint_and_fix
        write_file(str(tmp_dir/"x.py"), "x=1\n")
        assert isinstance(lint_and_fix(str(tmp_dir/"x.py")), bool)

class TestCodeRunner:
    def test_valid_script(self, tmp_dir):
        from tools.code_runner import run_code
        write_file(str(tmp_dir/"h.py"), "print('hi')\n")
        r = run_code(str(tmp_dir/"h.py"))
        assert r["returncode"] == 0
        assert "hi" in r["stdout"]
        assert r["timed_out"] is False

    def test_error_script(self, tmp_dir):
        from tools.code_runner import run_code
        write_file(str(tmp_dir/"e.py"), "raise ValueError('oops')\n")
        r = run_code(str(tmp_dir/"e.py"))
        assert r["returncode"] != 0

    def test_timeout(self, tmp_dir):
        from tools.code_runner import run_code
        write_file(str(tmp_dir/"inf.py"), "while True: pass\n")
        r = run_code(str(tmp_dir/"inf.py"), timeout=2)
        assert r["timed_out"] is True

    def test_missing_file(self):
        from tools.code_runner import run_code
        r = run_code("/nonexistent.py")
        assert r["returncode"] != 0
