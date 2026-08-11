from pathlib import Path

from app_version import __version__


ROOT = Path(__file__).resolve().parents[1]


def test_version_sources_and_user_documentation_are_synchronized():
    version = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
    assert version == __version__ == "0.5.0"
    user_guide = (ROOT / "README_用户说明.md").read_text(
        encoding="utf-8"
    )
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"v{version}" in user_guide
    assert f"v{version}" in changelog


def test_handoff_contains_all_required_sections_without_source_dump():
    handoff = (ROOT / "PROJECT_HANDOFF.md").read_text(encoding="utf-8")
    required = [
        "项目目标",
        "当前版本号",
        "技术栈",
        "关键目录和入口文件",
        "PMSM核心公式与单位约定",
        "默认参数",
        "两种输入模式",
        "MTPA/弱磁/MTPV分类规则",
        "当前已完成功能",
        "本次修改内容",
        "已知问题",
        "测试和打包命令",
        "下一步建议",
        "最近一次测试结果",
        "最近一次发布包位置和大小",
    ]
    assert all(section in handoff for section in required)
    assert len(handoff) < 6000


def test_release_script_and_spec_exclude_development_content():
    script = (ROOT / "build_release.ps1").read_text(encoding="utf-8")
    spec = (ROOT / "PMSMPerformanceTool.spec").read_text(encoding="utf-8")
    assert "pytest -q" in script
    assert "--smoke-test" in script
    assert "Compress-Archive" in script
    assert "Get-FileHash" in script
    for excluded in (
        "QtWebEngine",
        "QtQml",
        "QtMultimedia",
        "matplotlib",
        "jupyter",
        "pytest",
    ):
        assert excluded in spec
