from griga import __version__
from griga.interfaces.cli import main


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


def test_chat_is_not_implemented_yet(capsys):
    assert main(["chat"]) == 2
    assert "не реализован" in capsys.readouterr().out
