import unittest

from services.lolban_service import clean_payload, format_lolban_text


class LolBanReasonOutputTests(unittest.TestCase):
    def test_current_production_shape_outputs_reason_without_source(self):
        payload = clean_payload(
            "97077000",
            {
                "code": 200,
                "by": "q.lolmap.cn",
                "data": {
                    "qq": "97077000",
                    "ban_time": "2031-1-2 14:03:37",
                    "end_time": "1987天2小时32分41秒",
                    "ban_reason": "游戏环境异常：检测到违规软件加载",
                    "status": "封禁",
                },
                "msg": "此账号已被封禁",
            },
        )

        text = format_lolban_text(payload)

        self.assertIn("封禁原因：游戏环境异常：检测到违规软件加载", text)
        self.assertIn("封禁时间：2031-1-2 14:03:37", text)
        self.assertIn("剩余时间：1987天2小时32分41秒", text)
        self.assertNotIn("q.lolmap.cn", text)
        self.assertNotIn("接口来源", text)
        self.assertNotIn("Provider", text)
        self.assertEqual(payload["by"], "configured-provider")

    def test_missing_reason_is_explicit(self):
        payload = clean_payload(
            "97077000",
            {
                "code": 200,
                "data": {"qq": "97077000", "status": "封禁"},
                "msg": "此账号已被封禁",
            },
        )

        self.assertIn("第三方接口未提供封禁原因", format_lolban_text(payload))

    def test_normal_account_does_not_render_reason(self):
        payload = clean_payload(
            "97077000",
            {
                "code": 200,
                "data": {"qq": "97077000", "status": "正常"},
                "msg": "此账号状态正常",
            },
        )

        text = format_lolban_text(payload)
        self.assertIn("账号状态：正常", text)
        self.assertNotIn("封禁原因", text)


if __name__ == "__main__":
    unittest.main()
