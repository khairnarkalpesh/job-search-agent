import json

from http_client import HttpClient


def counting_client(cache_dir=None):
    client = HttpClient(cache_dir=cache_dir)
    client.calls = []
    client.get = lambda url, check_robots=False: client.calls.append(url) or json.dumps({"n": len(client.calls)})
    return client


def test_cached_json_is_reused_and_uncached_is_not(tmp_path):
    client = counting_client(tmp_path)
    assert client.get_json("https://a.example/x", cache_hours=6) == {"n": 1}
    assert client.get_json("https://a.example/x", cache_hours=6) == {"n": 1}
    assert client.get_json("https://a.example/x") == {"n": 2}
    assert len(client.calls) == 2


def test_no_cache_dir_means_no_cache():
    client = counting_client()
    client.get_json("https://a.example/x", cache_hours=6)
    client.get_json("https://a.example/x", cache_hours=6)
    assert len(client.calls) == 2
