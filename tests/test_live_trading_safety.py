import importlib
import os
import sys
import types
import unittest
from unittest.mock import patch


class _DummyApiCreds:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _DummyOrderArgs:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _DummyMarketOrderArgs:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _DummyOrderType:
    FOK = "FOK"
    GTC = "GTC"


def _install_dependency_stubs():
    requests_module = types.ModuleType("requests")
    requests_module.get = lambda *args, **kwargs: None

    py_clob_client_module = types.ModuleType("py_clob_client")
    client_module = types.ModuleType("py_clob_client.client")
    clob_types_module = types.ModuleType("py_clob_client.clob_types")

    client_module.ClobClient = object
    clob_types_module.ApiCreds = _DummyApiCreds
    clob_types_module.MarketOrderArgs = _DummyMarketOrderArgs
    clob_types_module.OrderArgs = _DummyOrderArgs
    clob_types_module.OrderType = _DummyOrderType

    sys.modules.setdefault("requests", requests_module)
    sys.modules.setdefault("py_clob_client", py_clob_client_module)
    sys.modules.setdefault("py_clob_client.client", client_module)
    sys.modules.setdefault("py_clob_client.clob_types", clob_types_module)


def _load_bot(env):
    _install_dependency_stubs()
    for name in (
        "PRIVATE_KEY",
        "CHAIN_ID",
        "SIGNATURE_TYPE",
        "PROXY_KEY",
        "WALLET_ADDRESS",
        "POLY_API_KEY",
        "POLY_SECRET",
        "POLY_PASSPHRASE",
    ):
        os.environ.pop(name, None)
    os.environ.update(env)
    sys.modules.pop("bot_v2", None)
    return importlib.import_module("bot_v2")


class LiveTradingSafetyTests(unittest.TestCase):
    def test_live_trading_requires_all_clob_credentials(self):
        bot = _load_bot({"PRIVATE_KEY": "set", "POLY_API_KEY": "set"})

        self.assertFalse(bot.LIVE_TRADING)
        self.assertIn("POLY_SECRET", bot.LIVE_CONFIG_ERRORS)
        self.assertIn("POLY_PASSPHRASE", bot.LIVE_CONFIG_ERRORS)
        self.assertIn("PROXY_KEY or WALLET_ADDRESS", bot.LIVE_CONFIG_ERRORS)

    def test_order_response_success_requires_explicit_success_and_order_id(self):
        bot = _load_bot({})

        self.assertFalse(bot.live_order_succeeded({"success": False, "orderID": "abc"}))
        self.assertFalse(bot.live_order_succeeded({"success": True}))
        self.assertFalse(bot.live_order_succeeded({"success": True, "errorMsg": "rejected", "orderID": "abc"}))
        self.assertTrue(bot.live_order_succeeded({"success": True, "orderID": "abc"}))

    def test_live_buy_rejects_unsuccessful_clob_response(self):
        bot = _load_bot({
            "PRIVATE_KEY": "set",
            "POLY_API_KEY": "set",
            "POLY_SECRET": "set",
            "POLY_PASSPHRASE": "set",
            "PROXY_KEY": "0xproxy",
        })

        class FakeClient:
            def create_market_order(self, args):
                return {"signed": True}

            def post_order(self, signed, order_type):
                return {"success": False, "orderID": "abc"}

        with patch.object(bot, "get_clob", return_value=FakeClient()):
            self.assertFalse(bot.place_live_buy("token", 0.25, 1.00))

    def test_live_buy_uses_installed_clob_create_order_api(self):
        bot = _load_bot({
            "PRIVATE_KEY": "set",
            "POLY_API_KEY": "set",
            "POLY_SECRET": "set",
            "POLY_PASSPHRASE": "set",
            "PROXY_KEY": "0xproxy",
        })

        class FakeClient:
            def __init__(self):
                self.created = False

            def create_market_order(self, args):
                self.created = True
                return {"signed": True}

            def post_order(self, signed, order_type):
                return {"success": True, "orderID": "abc"}

        fake = FakeClient()

        with patch.object(bot, "get_clob", return_value=fake):
            self.assertTrue(bot.place_live_buy("token", 0.25, 1.00))
        self.assertTrue(fake.created)

    def test_live_buy_uses_market_order_amount_with_cent_precision(self):
        bot = _load_bot({
            "PRIVATE_KEY": "set",
            "POLY_API_KEY": "set",
            "POLY_SECRET": "set",
            "POLY_PASSPHRASE": "set",
            "PROXY_KEY": "0xproxy",
        })

        class FakeClient:
            def __init__(self):
                self.order_args = None

            def create_market_order(self, args):
                self.order_args = args
                return {"signed": True}

            def post_order(self, signed, order_type):
                return {"success": True, "orderID": "abc"}

        fake = FakeClient()

        with patch.object(bot, "get_clob", return_value=fake):
            self.assertTrue(bot.place_live_buy("token", 0.3333333, 1.999999))

        self.assertEqual(fake.order_args.kwargs["amount"], 2.00)
        self.assertEqual(fake.order_args.kwargs["price"], 0.3333)
        self.assertEqual(fake.order_args.kwargs["order_type"], bot.OrderType.FOK)

    def test_live_buy_retries_transient_clob_request_exception(self):
        bot = _load_bot({
            "PRIVATE_KEY": "set",
            "POLY_API_KEY": "set",
            "POLY_SECRET": "set",
            "POLY_PASSPHRASE": "set",
            "PROXY_KEY": "0xproxy",
        })

        class RequestException(Exception):
            status_code = None

            def __str__(self):
                return "PolyApiException[status_code=None, error_message=Request exception!]"

        class FakeClient:
            def __init__(self):
                self.posts = 0

            def create_market_order(self, args):
                return {"signed": True}

            def post_order(self, signed, order_type):
                self.posts += 1
                if self.posts == 1:
                    raise RequestException()
                return {"success": True, "orderID": "abc"}

        fake = FakeClient()

        with patch.object(bot, "get_clob", return_value=fake), patch.object(bot.time, "sleep"):
            self.assertTrue(bot.place_live_buy("token", 0.25, 1.00))

        self.assertEqual(fake.posts, 2)

    def test_resolve_retries_gamma_timeout(self):
        bot = _load_bot({})

        class FakeResponse:
            def json(self):
                return {"closed": False}

        calls = {"count": 0}

        def fake_get(url, timeout):
            calls["count"] += 1
            if calls["count"] == 1:
                raise TimeoutError("Read timed out")
            return FakeResponse()

        with patch.object(bot.requests, "get", side_effect=fake_get), patch.object(bot.time, "sleep"):
            self.assertIsNone(bot.check_market_resolved("2057076"))

        self.assertEqual(calls["count"], 2)

    def test_live_buy_treats_fok_not_filled_as_skip(self):
        bot = _load_bot({
            "PRIVATE_KEY": "set",
            "POLY_API_KEY": "set",
            "POLY_SECRET": "set",
            "POLY_PASSPHRASE": "set",
            "PROXY_KEY": "0xproxy",
        })

        class FokNotFilled(Exception):
            status_code = 400
            error_msg = {
                "error": "order couldn't be fully filled. FOK orders are fully filled or killed.",
                "orderID": "0xabc",
            }

        class FakeClient:
            def create_market_order(self, args):
                return {"signed": True}

            def post_order(self, signed, order_type):
                raise FokNotFilled()

        with patch.object(bot, "get_clob", return_value=FakeClient()):
            self.assertFalse(bot.place_live_buy("token", 0.25, 1.00))


if __name__ == "__main__":
    unittest.main()
