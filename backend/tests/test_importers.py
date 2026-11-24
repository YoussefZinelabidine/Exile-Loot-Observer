"""Importer tests. Everything is offline: ``httpx.MockTransport`` serves recorded excerpts."""

import json
from pathlib import Path

import httpx
import pytest

from backend.importers import checks, poere, repoe, run, skilltree, tiers, translations
from backend.importers.errors import ImporterError, MissingContactInfoError
from backend.importers.http import build_data_user_agent, make_client
from backend.importers.store import DataStore, sha256_hex

FIX = Path(__file__).parent / "fixtures" / "importers"
REPO_ROOT = Path(__file__).resolve().parents[2]
PATCH_JSON = json.loads(
    (REPO_ROOT / "shared" / "fixtures" / "snapshot" / "patch.json").read_text(encoding="utf-8")
)
UA = "ELO/test (+https://example.invalid/elo; contact: ops@example.invalid)"


def fx(*parts: str) -> bytes:
    return FIX.joinpath(*parts).read_bytes()


@pytest.fixture
def alerts(_no_alerts_no_webhooks):
    """The alerts recorded by the autouse stub in backend/conftest.py."""
    return _no_alerts_no_webhooks


def make_test_client(routes: dict[str, bytes | int], seen: list | None = None):
    """Client whose transport answers from ``routes`` (URL -> body or status code)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        answer = routes.get(str(request.url))
        if answer is None:
            return httpx.Response(404)
        if isinstance(answer, int):
            return httpx.Response(answer)
        return httpx.Response(200, content=answer)

    return make_client(UA, transport=httpx.MockTransport(handler))


def repoe_routes() -> dict[str, bytes | int]:
    routes: dict[str, bytes | int] = {f"{repoe.BASE_URL}/version.txt": fx("repoe", "version.txt")}
    for name in repoe.JSON_FILES:
        routes[f"{repoe.BASE_URL}/{name}"] = fx("repoe", name)
    return routes


def poere_routes(
    *, tamper: bool = False, listed: bool = True, full: bool = True
) -> dict[str, bytes | int]:
    if full:  # every scored item class present
        groups = [{"basetype": b, "categoryRegex": []} for b in checks.SCORED_CLASSES.values()]
        items = json.dumps(groups).encode()
    else:  # the recorded excerpt: Rings and Amulets only
        items = fx("poere", "Generated.Item.ENGLISH.min.json")
    digest = sha256_hex(items)
    path = "item/Generated.Item.ENGLISH.min.json" if listed else "item/other.json"
    sums = f"{'1' * 64}  elsewhere.json\n{digest}  {path}\n".encode()
    base = poere.BASE_URL
    return {
        f"{base}/current.json": fx("poere", "current.json"),
        f"{base}/generated/poe1/3.30.0.4.3/SHA256SUMS": sums,
        f"{base}/generated/poe1/3.30.0.4.3/item/Generated.Item.ENGLISH.min.json": items
        + (b" " if tamper else b""),
    }


def skilltree_routes() -> dict[str, bytes | int]:
    sha = json.loads(fx("skilltree", "commit.json"))["sha"]
    return {
        f"{skilltree.API_URL}/repos/{skilltree.REPO}/commits/{skilltree.BRANCH}": fx(
            "skilltree", "commit.json"
        ),
        f"{skilltree.RAW_URL}/{skilltree.REPO}/{sha}/data.json": fx("skilltree", "data.json"),
    }


# ---------------------------------------------------------------- user agent


def test_user_agent_formats():
    full = build_data_user_agent(contact_email="a@b.c", project_url="https://x.y", version="1.2")
    assert full == "ELO/1.2 (+https://x.y; contact: a@b.c)"
    assert build_data_user_agent(contact_email="", project_url="https://x.y", version="1.2") == (
        "ELO/1.2 (+https://x.y)"
    )
    with pytest.raises(MissingContactInfoError):
        build_data_user_agent(contact_email="a@b.c", project_url=None)


def test_requests_carry_the_user_agent(tmp_path):
    seen: list[httpx.Request] = []
    client = make_test_client(repoe_routes(), seen)
    repoe.import_repoe(client, DataStore(tmp_path))
    assert seen and all(r.headers["user-agent"] == UA for r in seen)


# ---------------------------------------------------------------- store


def test_store_commit_is_atomic_and_listed(tmp_path):
    store = DataStore(tmp_path)
    listing = store.commit("repoe", "1.0", {"a.json": b"{}", "b.txt": b"x"})
    assert {e["path"] for e in listing} == {"a.json", "b.txt"}
    assert store.read("repoe", "1.0", "a.json") == b"{}"
    assert [p.name for p in (tmp_path / "repoe").iterdir()] == ["1.0"]
    with pytest.raises(ImporterError):
        store.commit("repoe", "1.0", {"a.json": b"{}"})
    with pytest.raises(ImporterError):
        store.commit("repoe", "../evil", {"a.json": b"{}"})
    with pytest.raises(ImporterError):
        store.commit("repoe", "2.0", {"../a.json": b"{}"})
    assert store.active_version("repoe") is None
    store.set_active("repoe", "1.0")
    assert store.active_version("repoe") == "1.0"
    with pytest.raises(ImporterError):
        store.set_active("repoe", "9.9")


# ---------------------------------------------------------------- RePoE


def test_repoe_import_stages_all_files(tmp_path, alerts):
    store = DataStore(tmp_path)
    result = repoe.import_repoe(make_test_client(repoe_routes()), store)
    assert (result.status, result.version) == ("staged", "3.30.0.4.3")
    assert {f["path"] for f in result.files} == {"version.txt", *repoe.JSON_FILES}
    assert store.active_version("repoe") is None  # staging never activates
    assert "Diamond Ring" in {
        b["name"] for b in repoe.load(store, result.version, "base_items.json").values()
    }
    again = repoe.import_repoe(make_test_client(repoe_routes()), store)
    assert again.status == "unchanged"
    assert alerts == []


def test_repoe_failure_keeps_last_good_copy(tmp_path, alerts):
    store = DataStore(tmp_path)
    store.commit("repoe", "3.29.0.0.1", {"mods.json": b"{}"})
    store.set_active("repoe", "3.29.0.0.1")
    routes = repoe_routes()
    routes[f"{repoe.BASE_URL}/gems.json"] = 500
    result = repoe.import_repoe(make_test_client(routes), store)
    assert result.status == "failed"
    assert not store.has_version("repoe", "3.30.0.4.3")
    assert not [p for p in (tmp_path / "repoe").iterdir() if p.name.startswith(".tmp")]
    assert store.active_version("repoe") == "3.29.0.0.1"
    assert len(alerts) == 1


def test_repoe_invalid_json_is_rejected_as_failure(tmp_path, alerts):
    routes = repoe_routes()
    routes[f"{repoe.BASE_URL}/mods.json"] = b"not json"
    result = repoe.import_repoe(make_test_client(routes), DataStore(tmp_path))
    assert result.status == "failed" and alerts


def test_repoe_parsers_on_excerpts():
    mods = repoe.parse_json_file("mods.json", fx("repoe", "mods.json"))
    assert "IncreasedLife1" in mods or any(k.startswith("IncreasedLife") for k in mods)
    for name in repoe.JSON_FILES:
        repoe.parse_json_file(name, fx("repoe", name))
    with pytest.raises(ImporterError):
        repoe.parse_json_file("mods.json", b"[]")
    with pytest.raises(ImporterError):
        repoe.parse_version(b"  \n")


# ---------------------------------------------------------------- poe.re


def test_poere_import_verifies_checksum(tmp_path, alerts):
    store = DataStore(tmp_path)
    result = poere.import_poere(make_test_client(poere_routes()), store)
    assert (result.status, result.version) == ("staged", "3.30.0.4.3")
    assert result.commit == "17bc109"
    assert {g["basetype"] for g in poere.load_items(store, result.version)} == set(
        checks.SCORED_CLASSES.values()
    )
    assert alerts == []


def test_poere_checksum_mismatch_is_rejected(tmp_path, alerts):
    store = DataStore(tmp_path)
    result = poere.import_poere(make_test_client(poere_routes(tamper=True)), store)
    assert result.status == "rejected" and result.version == "3.30.0.4.3"
    assert not store.has_version("poere", "3.30.0.4.3")
    assert len(alerts) == 1


def test_poere_missing_checksum_entry_is_rejected(tmp_path, alerts):
    result = poere.import_poere(make_test_client(poere_routes(listed=False)), DataStore(tmp_path))
    assert result.status == "rejected" and alerts


def test_poere_parsers():
    assert poere.parse_current(fx("poere", "current.json")) == ("3.30.0.4.3", "17bc109")
    with pytest.raises(ImporterError):
        poere.parse_current(b'{"poe1": "3.30.0.4.3"}')
    with pytest.raises(ImporterError):
        poere.parse_current(b'{"current": {"poe1": {"patch": "bad"}}}')
    sums = poere.parse_sha256sums(fx("poere", "SHA256SUMS"))
    assert "item/Generated.Item.ENGLISH.min.json" in sums


# ---------------------------------------------------------------- skill tree


def test_skilltree_import_records_commit_as_version(tmp_path, alerts):
    store = DataStore(tmp_path)
    result = skilltree.import_skilltree(make_test_client(skilltree_routes()), store)
    assert (result.status, result.version) == ("staged", "0123456789ab")
    assert json.loads(store.read("skilltree", "0123456789ab", "data.json"))["nodes"]
    assert (
        skilltree.import_skilltree(make_test_client(skilltree_routes()), store).status
        == "unchanged"
    )


def test_skilltree_failure_keeps_nothing(tmp_path, alerts):
    routes = skilltree_routes()
    routes[f"{skilltree.API_URL}/repos/{skilltree.REPO}/commits/{skilltree.BRANCH}"] = b"{}"
    result = skilltree.import_skilltree(make_test_client(routes), DataStore(tmp_path))
    assert result.status == "failed" and alerts


# ---------------------------------------------------------------- cross checks


def test_patch_mismatch_is_reported(alerts):
    assert checks.check_patch_versions("3.30.0.4.3", "3.30.0.4.3") is True
    assert alerts == []
    assert checks.check_patch_versions("3.30.0.4.3", "3.31.0.1.0") is False
    assert len(alerts) == 1


def test_missing_scored_classes_listed():
    items = poere.parse_items(fx("poere", "Generated.Item.ENGLISH.min.json"))
    missing = checks.missing_scored_classes(items)
    assert missing == sorted(set(checks.SCORED_CLASSES) - {"Ring", "Amulet"})
    assert checks.missing_scored_classes(items, {"Ring": "Rings"}) == []


# ---------------------------------------------------------------- tier ladders


def test_tier_ladders_match_fixture_patch():
    mods = json.loads(fx("repoe", "mods.json"))
    bases = json.loads(fx("repoe", "base_items.json"))
    base = tiers.find_base(bases, "Diamond Ring")
    assert base["drop_level"] == PATCH_JSON["bases"]["Diamond Ring"]["drop_level"]
    assert tiers.tier_set_id(base) == PATCH_JSON["bases"]["Diamond Ring"]["tier_set"]
    built = tiers.build_tier_set(mods, base)
    expected_all = PATCH_JSON["tier_sets"][tiers.tier_set_id(base)]
    assert set(built) == {
        "prefix:IncreasedLife",
        "suffix:IncreasedAccuracy",
        "suffix:ChaosResistance",
    }
    for key, family in built.items():
        assert family == expected_all[key], key


def test_tier_ladder_excludes_decoys():
    mods = json.loads(fx("repoe", "mods.json"))
    base = tiers.find_base(json.loads(fx("repoe", "base_items.json")), "Diamond Ring")
    ids = {t["mod_id"] for t in tiers.build_tier_set(mods, base)["prefix:IncreasedLife"]["tiers"]}
    for decoy in (
        "IncreasedLifeCrafted",
        "IncreasedLifeEssence",
        "IncreasedLifeRoyale1",
        "IncreasedLifeFirstTagZero",
        "IncreasedLifeOtherBase",
        "IncreasedLifeCorrupted",
        "IncreasedLifeFlask",
    ):
        assert decoy not in ids
    levels = [
        t["required_level"]
        for t in tiers.build_tier_set(mods, base)["prefix:IncreasedLife"]["tiers"]
    ]
    assert levels == sorted(levels, reverse=True)


# ---------------------------------------------------------------- stat text


def test_markup_reduced_to_text():
    assert translations.clean_markup("[Life|Maximum Life] and [Resistances] x") == (
        "Maximum Life and Resistances x"
    )
    assert translations.clean_markup("no markup {0}%") == "no markup {0}%"


def test_translations_and_trade_ids_match_fixture_patch():
    st = json.loads(fx("repoe", "stat_translations.json"))
    ids = {"base_maximum_life", "accuracy_rating", "base_chaos_damage_resistance_%"}
    built = translations.build_translations(st, ids)
    by_id = {t["ids"][0]: t for t in PATCH_JSON["translations"]}
    assert {t["ids"][0] for t in built} == ids
    for entry in built:
        assert entry == by_id[entry["ids"][0]]
    trade = translations.build_trade_ids(st, ids)
    for sid in ids:
        assert trade[sid] == PATCH_JSON["trade_ids"][sid]
    marked = translations.build_translations(st, {"markup_example"})
    assert marked[0]["english"][0]["string"] == "Maximum Life and Resistances near Critical"


# ---------------------------------------------------------------- run_all


def all_routes(items: bytes | None = None) -> dict[str, bytes | int]:
    routes = {**repoe_routes(), **poere_routes(full=False), **skilltree_routes()}
    if items is not None:
        base = f"{poere.BASE_URL}/generated/poe1/3.30.0.4.3"
        routes[f"{base}/item/Generated.Item.ENGLISH.min.json"] = items
        sums = f"{sha256_hex(items)}  item/Generated.Item.ENGLISH.min.json\n".encode()
        routes[f"{base}/SHA256SUMS"] = sums
    return routes


def test_run_all_rejects_poere_missing_scored_classes(tmp_path, alerts):
    store = DataStore(tmp_path)
    for run_number in (1, 2):
        alerts.clear()
        results = run.run_all(store, make_test_client(all_routes()))
        by_source = {r.source: r for r in results}
        assert by_source["poere"].status == "rejected", run_number
        assert "Boots" in by_source["poere"].message
        assert any("missing" in a for a in alerts)
        assert not store.has_version("poere", "3.30.0.4.3")  # nothing written on rejection
    assert by_source["repoe"].status == "unchanged"  # second run: already stored
    assert by_source["skilltree"].status == "unchanged"
    with pytest.raises(ImporterError):
        store.set_active("poere", "3.30.0.4.3")


def test_run_all_accepts_poere_with_every_scored_class(tmp_path, alerts):
    groups = [{"basetype": b, "categoryRegex": []} for b in checks.SCORED_CLASSES.values()]
    items = json.dumps(groups).encode()
    results = run.run_all(DataStore(tmp_path), make_test_client(all_routes(items)))
    assert [r.status for r in results] == ["staged", "staged", "staged"]
    assert alerts == []


class CrashingStore(DataStore):
    def commit(self, source, version, files):
        if source == "repoe":
            raise RuntimeError("boom")
        return super().commit(source, version, files)


def test_unexpected_error_in_one_importer_does_not_stop_the_others(tmp_path, alerts):
    results = run.run_all(CrashingStore(tmp_path), make_test_client(all_routes()))
    by_source = {r.source: r for r in results}
    assert by_source["repoe"].status == "failed"
    assert by_source["skilltree"].status == "staged"
    assert any("repoe" in a for a in alerts)


def test_invalid_utf8_and_invalid_url_become_failed_with_alert(tmp_path, alerts):
    routes = repoe_routes()
    routes[f"{repoe.BASE_URL}/version.txt"] = b"\xff\xfe\x00bad"
    result = repoe.import_repoe(make_test_client(routes), DataStore(tmp_path))
    assert result.status == "failed" and alerts

    def raise_invalid(request):
        raise httpx.InvalidURL("bad url")

    client = make_client(UA, transport=httpx.MockTransport(raise_invalid))
    alerts.clear()
    assert repoe.import_repoe(client, DataStore(tmp_path)).status == "failed" and alerts


def test_oserror_while_storing_becomes_failed_with_alert(tmp_path, alerts, monkeypatch):
    def broken_rename(self, target):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "rename", broken_rename)
    result = skilltree.import_skilltree(make_test_client(skilltree_routes()), DataStore(tmp_path))
    assert result.status == "failed" and alerts
    assert not [p for p in (tmp_path / "skilltree").iterdir() if p.name.startswith(".tmp")]


def test_repoe_version_changing_mid_download_fails(tmp_path, alerts):
    calls = {"n": 0}
    routes = repoe_routes()

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/version.txt"):
            calls["n"] += 1
            return httpx.Response(
                200, content=b"3.30.0.4.3\n" if calls["n"] == 1 else b"3.31.0.0.1\n"
            )
        body = routes.get(str(request.url))
        return httpx.Response(200, content=body) if isinstance(body, bytes) else httpx.Response(404)

    client = make_client(UA, transport=httpx.MockTransport(handler))
    store = DataStore(tmp_path)
    assert repoe.import_repoe(client, store).status == "failed"
    assert not store.has_version("repoe", "3.30.0.4.3")


def test_set_active_rejects_unsafe_source(tmp_path):
    with pytest.raises(ImporterError):
        DataStore(tmp_path).set_active("../x", "1")
