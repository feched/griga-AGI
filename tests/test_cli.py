from griga import __version__
from griga.interfaces.cli import build_parser, main


def test_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"griga {__version__}"


def test_status_reports_adr_parameters(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "Griga AGI v0.1" in out
    assert "D=0.85" in out
    assert "T=0.1" in out
    assert "eta=0.05" in out
    assert "perception:" in out
    assert "generation: max_attempts=3" in out


def test_chat_command_and_single_text_option_are_available():
    args = build_parser().parse_args(["chat", "--text", "Привет!"])
    assert args.command == "chat"
    assert args.text == "Привет!"
