"""Synced from upstream packages/shared/tests/unit-test/env/helper.test.ts."""

from midscene.shared.env.helper import mask_config


def test_key_will_be_masked():
    """key will be masked"""
    config = {
        "modelName": "test-model",
        "openaiApiKey": "sk-thisisafakekeythatislongenough",
        "socksProxy": "socks://proxy.example.com:1080",
        "httpProxy": "http://proxy.example.com:8080",
        "openaiBaseURL": "https://api.openai.com/v1",
        "openaiExtraConfig": {"top_p": 0.9},
        "modelFamily": "doubao-vision",
        "modelDescription": "",
        "intent": "default",
        "slot": "default",
    }

    assert mask_config(config) == {
        "httpProxy": "http://proxy.example.com:8080",
        "intent": "default",
        "slot": "default",
        "modelDescription": "",
        "modelName": "test-model",
        "openaiApiKey": "sk-***************************ugh",
        "openaiBaseURL": "https://api.openai.com/v1",
        "openaiExtraConfig": {"top_p": 0.9},
        "socksProxy": "socks://proxy.example.com:1080",
        "modelFamily": "doubao-vision",
    }
