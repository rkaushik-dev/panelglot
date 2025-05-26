import shutil

import pytest

from v4t_translate.config import load_config
from v4t_translate.errors import ConfigError
from v4t_translate.mt.http import HttpProvider
from v4t_translate.mt.providers import PseudoProvider
from v4t_translate.ops.doctor import run_doctor
from v4t_translate.ops.extract import extract_project
from v4t_translate.ops.pretranslate import build_provider

BASE = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]
"""

DEEPL = """
[provider.deepl]
endpoint = "https://api-free.deepl.com/v2/translate"
auth_header = "Authorization"
auth_prefix = "DeepL-Auth-Key "
auth_env = "DEEPL_API_KEY"
target_field = "target_lang"
target_style = "upper-language"
response_path = "translations[].text"
batch_size = 40
"""


def write(tmp_path, text):
    (tmp_path / "v4t-translate.toml").write_text(text, encoding="utf-8")
    return load_config(tmp_path / "v4t-translate.toml")


@pytest.fixture
def project(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    return tmp_path


def test_a_project_with_no_providers(project):
    assert write(project, BASE).providers == {}


def test_a_provider_is_read(project):
    config = write(project, BASE + DEEPL)
    entry = config.providers["deepl"]
    assert entry.endpoint.endswith("/v2/translate")
    assert entry.settings["auth_env"] == "DEEPL_API_KEY"
    assert entry.settings["batch_size"] == 40


def test_the_entry_describes_itself(project):
    config = write(project, BASE + DEEPL)
    assert config.providers["deepl"].describe().startswith("deepl -> https://")


def test_a_provider_with_no_endpoint(project):
    with pytest.raises(ConfigError, match="needs an endpoint"):
        write(project, BASE + '\n[provider.x]\nauth_env = "KEY"\n')


def test_an_endpoint_that_is_not_a_url(project):
    with pytest.raises(ConfigError, match="is not a URL"):
        write(project, BASE + '\n[provider.x]\nendpoint = "translate.sh"\n')


@pytest.mark.parametrize("field", ["key", "token", "api_key", "auth", "password"])
def test_a_secret_in_the_config_is_refused(project, field):
    text = BASE + f'\n[provider.x]\nendpoint = "https://a.test/t"\n{field} = "abc123"\n'
    with pytest.raises(ConfigError, match="goes in the repository"):
        write(project, text)


def test_the_refusal_says_what_to_do_instead(project):
    text = BASE + '\n[provider.x]\nendpoint = "https://a.test/t"\nkey = "abc"\n'
    with pytest.raises(ConfigError, match="auth_env"):
        write(project, text)


def test_a_provider_that_is_not_a_table(project):
    with pytest.raises(ConfigError, match="is not a table"):
        write(project, BASE + '\n[provider]\ndeepl = "https://a.test/t"\n')


def test_a_builtin_provider_is_built(project):
    config = write(project, BASE)
    assert isinstance(build_provider(config, "pseudo"), PseudoProvider)


def test_a_configured_provider_is_built(project):
    config = write(project, BASE + DEEPL)
    provider = build_provider(config, "deepl")
    assert isinstance(provider, HttpProvider)
    assert provider.config.batch_size == 40
    assert provider.config.target_style == "upper-language"


def test_a_builtin_name_wins_over_a_configured_one(project):
    # A project calling its engine "pseudo" would otherwise spend an
    # afternoon working out why every translation is covered in accents.
    text = BASE + '\n[provider.pseudo]\nendpoint = "https://a.test/t"\n'
    config = write(project, text)
    assert isinstance(build_provider(config, "pseudo"), PseudoProvider)


def test_an_unknown_provider_lists_both_kinds(project):
    config = write(project, BASE + DEEPL)
    with pytest.raises(ConfigError) as excinfo:
        build_provider(config, "nope")
    message = str(excinfo.value)
    assert "deepl" in message
    assert "pseudo" in message


def test_a_setting_the_provider_does_not_understand(project):
    text = BASE + '\n[provider.x]\nendpoint = "https://a.test/t"\nretries = 3\n'
    config = write(project, text)
    with pytest.raises(ConfigError, match="does not understand retries"):
        build_provider(config, "x")


def test_the_error_lists_the_settings_that_exist(project):
    text = BASE + '\n[provider.x]\nendpoint = "https://a.test/t"\nretries = 3\n'
    config = write(project, text)
    with pytest.raises(ConfigError, match="response_path"):
        build_provider(config, "x")


def test_doctor_reports_a_working_provider(project, monkeypatch):
    monkeypatch.setenv("DEEPL_API_KEY", "secret")
    config = write(project, BASE + DEEPL)
    extract_project(config)

    findings = [f for f in run_doctor(config).findings if f.name == "provider deepl"]
    assert findings and findings[0].ok


def test_doctor_notices_a_key_that_is_not_in_the_shell(project, monkeypatch):
    monkeypatch.delenv("DEEPL_API_KEY", raising=False)
    config = write(project, BASE + DEEPL)

    findings = [f for f in run_doctor(config).problems if f.name == "provider deepl"]
    assert findings
    assert "DEEPL_API_KEY is not set" in findings[0].detail
    assert "not in the config file" in findings[0].remedy


def test_doctor_notices_a_provider_that_cannot_be_built(project):
    text = BASE + '\n[provider.x]\nendpoint = "https://a.test/t"\nretries = 3\n'
    config = write(project, text)

    findings = [f for f in run_doctor(config).problems if f.name == "provider x"]
    assert findings
    assert "does not understand" in findings[0].detail


def test_doctor_is_quiet_about_a_project_with_no_providers(project):
    config = write(project, BASE)
    assert not [f for f in run_doctor(config).findings if f.name.startswith("provider")]
