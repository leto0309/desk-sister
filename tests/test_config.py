import json

from claude_pet.config import Config, load_config, save_config


def test_missing_and_corrupt_files_give_defaults(tmp_path):
    assert load_config(tmp_path / "none.json") == Config()
    bad = tmp_path / "bad.json"
    for content in ("{not json", "[1, 2]", '{"interval_sec": "fast"}'):
        bad.write_text(content, encoding="utf-8")
        assert load_config(bad) == Config()


def test_out_of_range_values_are_clamped_and_unknown_keys_ignored(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"interval_sec": 1, "model": "gpt", "timeout_sec": 99999, "extra": 1}), encoding="utf-8")
    config = load_config(path)
    assert config.interval_sec == 15 and config.model == "haiku" and config.timeout_sec == 600


def test_round_trip(tmp_path):
    path = tmp_path / "sub" / "config.json"
    config = Config(interval_sec=300, model="sonnet", paused=True, blocklist=["私密"], x=10, y=20)
    save_config(config, path)
    assert load_config(path) == config
    assert not path.with_suffix(".tmp").exists()


def test_wrong_blocklist_type_keeps_default_blocklist(tmp_path):
    from claude_pet.config import DEFAULT_BLOCKLIST

    path = tmp_path / "c.json"
    for bad in ({}, "bank", ["ok", 1], None):
        path.write_text(json.dumps({"blocklist": bad, "interval_sec": 300}), encoding="utf-8")
        config = load_config(path)
        assert config.blocklist == DEFAULT_BLOCKLIST and config.interval_sec == 300, bad
    path.write_text(json.dumps({"blocklist": []}), encoding="utf-8")
    assert load_config(path).blocklist == []  # an explicit empty list is the user's choice


def test_non_finite_numbers_fall_back_to_defaults(tmp_path):
    path = tmp_path / "c.json"
    for raw in ('{"interval_sec": 1e309}', '{"timeout_sec": -1e309}', '{"x": NaN}'):
        path.write_text(raw, encoding="utf-8")
        assert load_config(path) == Config(), raw


def test_calm_observer_settings_are_clamped(tmp_path):
    path = tmp_path / "c.json"
    raw = {"dwell_sec": -5, "failure_limit": 0, "failure_pause_min": 99999, "quiet_fullscreen": 0}
    path.write_text(json.dumps(raw), encoding="utf-8")
    config = load_config(path)
    assert (config.dwell_sec, config.failure_limit, config.failure_pause_min, config.quiet_fullscreen) == (0, 1, 1440, False)
    default = Config()
    assert (default.dwell_sec, default.failure_limit, default.failure_pause_min, default.quiet_fullscreen) == (20, 3, 30, True)
