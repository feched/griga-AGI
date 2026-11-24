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


def test_visualize_command_options_are_available():
    args = build_parser().parse_args(
        [
            "visualize",
            "--host",
            "127.0.0.1",
            "--port",
            "9000",
            "--no-browser",
            "--node",
            "трава",
        ]
    )
    assert args.command == "visualize"
    assert args.port == 9000
    assert args.no_browser is True
    assert args.node == "трава"


def test_user_option_is_available_for_chat_and_visualize():
    chat = build_parser().parse_args(["chat", "--user", "Алиса"])
    assert chat.user == "Алиса"

    visualize = build_parser().parse_args(["visualize", "--user", "Боб"])
    assert visualize.user == "Боб"

    users = build_parser().parse_args(["users"])
    assert users.command == "users"


def test_history_command_and_limit_option_are_available():
    args = build_parser().parse_args(["history", "--limit", "5"])
    assert args.command == "history"
    assert args.limit == 5

    default = build_parser().parse_args(["history"])
    assert default.limit == 20


def test_safety_command_shows_policy(capsys):
    assert main(["safety"]) == 0
    out = capsys.readouterr().out
    assert "Safety shell v0.1" in out
    assert "forbidden" in out
    assert "nodes<=40" in out
    assert "edges<=20" in out
