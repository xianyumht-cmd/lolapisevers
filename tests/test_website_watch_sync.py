from __future__ import annotations

import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lanzou_update_push_api_server import website_watch_sync as sync


CATALOG = '''
const i = (title, description, url, avatar, options = {}) => ({title,description,url,avatar});
const s = (id, title, icon, items) => ({id,title,icon,items});
const navDataTranslations = {
zh: { sections: [
  s("tools", "常用工具", "icon", [
    i("Alpha", "密码: 1234", "https://foo.lanzouq.com/s/alpha", "A"),
    i("Beta", "暂无密码", "https://foo.lanzn.com/s/beta", "B"),
    i("Hidden", "密码6666", "", "H", {"displayOnly": true}),
    i("Other", "", "https://example.com/", "X"),
    i("Duplicate", "", "https://foo.lanzouq.com/s/alpha", "A"),
  ]),
  s("more", "更多", "icon", [
    i("Gamma", "提取码：ABCD", "https://other.lanzoub.com/b123", "G")
  ])
]},
en: { sections: [
  s("tools", "Tools", "icon", [
    i("English", "Password", "https://en.lanzouq.com/s/only-english", "E")
  ])
}
};
export default navDataTranslations;
'''


class CatalogTests(unittest.TestCase):
    def test_chinese_only_with_duplicate_and_display_only(self):
        with patch.object(sync, "MIN_TARGETS", 2):
            targets = sync.parse_catalog(CATALOG)
        self.assertEqual([x["title"] for x in targets], ["Duplicate", "Beta", "Gamma"])
        self.assertEqual([x["password"] for x in targets], ["", "", "ABCD"])
        self.assertEqual(targets[2]["section"], "更多")

    def test_fail_closed_on_broken_source(self):
        with patch.object(sync, "MIN_TARGETS", 2):
            with self.assertRaises(sync.WebsiteSyncError):
                sync.parse_catalog('export default { zh: { sections: [] }};')
            with self.assertRaises(sync.WebsiteSyncError):
                sync.parse_catalog(CATALOG.replace('i("Gamma"', 'i(getTitle()'))

    def test_fetches_sha_pinned_private_catalog_and_never_returns_token(self):
        commit = "a" * 40
        responses = [
            {"commit": {"sha": commit}},
            {"encoding": "base64", "content": base64.b64encode(CATALOG.encode()).decode()},
        ]
        with patch.object(sync, "MIN_TARGETS", 2), patch.object(sync, "configured_token", return_value="test-private-token"), patch.object(sync, "_get_json", side_effect=responses) as get:
            manifest = sync.fetch_manifest()
        self.assertEqual(manifest["sha"], commit)
        self.assertEqual(len(manifest["targets"]), 3)
        self.assertNotIn("test-private-token", json.dumps(manifest))
        self.assertEqual(get.call_args_list[0].args[0], "/repos/xianyumht-cmd/website/branches/source")
        self.assertEqual(get.call_args_list[1].args[0], "/repos/xianyumht-cmd/website/contents/src/assets/data/nav-catalog.js?ref=" + commit)

    def test_no_token_no_network(self):
        with patch.object(sync, "configured_token", return_value=""), patch.object(sync, "_get_json") as get:
            with self.assertRaisesRegex(sync.WebsiteSyncError, "Token"):
                sync.fetch_manifest()
            get.assert_not_called()

    def test_reads_uncommitted_local_secret_without_exposing_it(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "app_env.local.ps1"
            path.write_text('$env:WEBSITE_GITHUB_TOKEN = "github_pat_example123"\n', encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True), patch.object(sync.management, "APP_ENV_PATH", path):
                self.assertEqual(sync.configured_token(), "github_pat_example123")


class SyncPlanTests(unittest.TestCase):
    def test_preserves_password_flags_and_monitor_settings(self):
        old = [{
            "id": "existing-id", "title": "Old", "url": "https://foo.lanzn.com/s/a",
            "password": "secret1", "enabled": False, "max_pages": 8,
        }, {
            "id": "remove-me", "title": "Obsolete", "url": "https://foo.lanzn.com/s/old",
            "password": "secret2", "enabled": True, "max_pages": 20,
        }]
        manifest = {"sha": "a" * 40, "targets": [
            {"title": "Updated", "url": "https://foo.lanzn.com/s/a", "password": ""},
            {"title": "New", "url": "https://foo.lanzn.com/s/new", "password": "code"},
        ]}
        original = json.dumps(old)
        result = sync.plan_sync(old, manifest)
        self.assertEqual(json.dumps(old), original)
        self.assertEqual(result["watchers"][0]["id"], "existing-id")
        self.assertEqual(result["watchers"][0]["password"], "secret1")
        self.assertFalse(result["watchers"][0]["enabled"])
        self.assertEqual(result["watchers"][0]["max_pages"], 8)
        self.assertEqual(result["watchers"][1]["password"], "code")
        self.assertTrue(result["watchers"][1]["id"].startswith("nav-"))
        self.assertEqual([len(result["diff"][key]) for key in ("added", "removed", "updated")], [1, 1, 1])
        self.assertNotIn("secret1", json.dumps(result["diff"]))
        self.assertEqual(result["revision"], sync.revision(old))

    def test_repeated_sync_is_idempotent(self):
        targets = [
            {"title": "Alpha", "url": "https://foo.lanzn.com/s/one", "password": ""},
            {"title": "Beta", "url": "https://foo.lanzn.com/s/two", "password": "123"},
        ]
        first = sync.plan_sync([], {"sha": "a" * 40, "targets": targets})
        second = sync.plan_sync(first["watchers"], {"sha": "a" * 40, "targets": targets})
        self.assertEqual(first["watchers"], second["watchers"])
        for change in ("added", "removed", "updated"):
            self.assertEqual(second["diff"][change], [])


if __name__ == "__main__":
    unittest.main()
