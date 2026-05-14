import random
import json

from curl_cffi import requests

from .verify import CHALLENGE_TYPES, MP_VERIFY
from .fingerprint import get_fp


class UnsupportedChallengeError(RuntimeError):
    """AWS WAF returned a challenge type the Python port does not solve
    (currently: image-grid `mp_verify`). Callers should fall back to a
    vision-based puzzle solver and retry the page fetch."""


class AwsWaf:
    def __init__(self, goku_props: str,
                 endpoint: str,
                 domain: str,
                 user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
                 ):
        self.session = requests.Session(impersonate="chrome")
        self.session.headers = {
            "connection": "keep-alive",
            "sec-ch-ua-platform": "\"Windows\"",
            "user-agent": user_agent,
            "sec-ch-ua": "\"Chromium\";v=\"136\", \"Google Chrome\";v=\"136\", \"Not.A/Brand\";v=\"99\"",
            "sec-ch-ua-mobile": "?0",
            "accept": "*/*",
            "sec-fetch-site": "cross-site",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "en-US,en;q=0.9"
        }
        self.goku_props = goku_props
        self.user_agent = user_agent
        self.domain = domain
        self.endpoint = endpoint

    @staticmethod
    def extract(html: str):
        """Pull goku_props + challenge host out of an AWS WAF challenge
        HTML response. Raises ValueError if the page isn't a WAF challenge."""
        try:
            goku_props = json.loads(html.split("window.gokuProps = ")[1].split(";")[0])
            host = html.split("src=\"https://")[1].split("/challenge.js")[0]
        except (IndexError, json.JSONDecodeError) as exc:
            raise ValueError("page does not look like an AWS WAF challenge") from exc
        return goku_props, host

    def get_inputs(self):
        return self.session.get(
            f"https://{self.endpoint}/inputs?client=browser").json()

    def build_payload(self, inputs: dict):
        verify = CHALLENGE_TYPES[inputs["challenge_type"]]
        if verify == MP_VERIFY:
            raise UnsupportedChallengeError(
                "AWS WAF served the image-grid (mp_verify) challenge; "
                "use a vision-based solver fallback"
            )
        checksum, fp = get_fp(self.user_agent)
        return {
            "challenge": inputs["challenge"],
            "checksum": checksum,
            "solution": verify(inputs["challenge"]["input"], checksum, inputs["difficulty"]),
            "signals": [{"name": "Zoey", "value": {"Present": fp}}],
            "existing_token": None,
            "client": "Browser",
            "domain": self.domain,
            "metrics": [
                {"name": "2", "value": random.uniform(0, 1), "unit": "2"},
                {"name": "100", "value": 0, "unit": "2"},
                {"name": "101", "value": 0, "unit": "2"},
                {"name": "102", "value": 0, "unit": "2"},
                {"name": "103", "value": 8, "unit": "2"},
                {"name": "104", "value": 0, "unit": "2"},
                {"name": "105", "value": 0, "unit": "2"},
                {"name": "106", "value": 0, "unit": "2"},
                {"name": "107", "value": 0, "unit": "2"},
                {"name": "108", "value": 1, "unit": "2"},
                {"name": "undefined", "value": 0, "unit": "2"},
                {"name": "110", "value": 0, "unit": "2"},
                {"name": "111", "value": 2, "unit": "2"},
                {"name": "112", "value": 0, "unit": "2"},
                {"name": "undefined", "value": 0, "unit": "2"},
                {"name": "3", "value": 4, "unit": "2"},
                {"name": "7", "value": 0, "unit": "4"},
                {"name": "1", "value": random.uniform(10, 20), "unit": "2"},
                {"name": "4", "value": 36.5, "unit": "2"},
                {"name": "5", "value": random.uniform(0, 1), "unit": "2"},
                {"name": "6", "value": random.uniform(50, 60), "unit": "2"},
                {"name": "0", "value": random.uniform(130, 140), "unit": "2"},
                {"name": "8", "value": 1, "unit": "4"},
            ],
        }

    def verify(self, payload):
        self.session.headers = {
            "connection": "keep-alive",
            "sec-ch-ua-platform": "\"Windows\"",
            "user-agent": self.user_agent,
            "sec-ch-ua": "\"Chromium\";v=\"136\", \"Google Chrome\";v=\"136\", \"Not.A/Brand\";v=\"99\"",
            "content-type": "text/plain;charset=UTF-8",
            "sec-ch-ua-mobile": "?0",
            "accept": "*/*",
            "sec-fetch-site": "cross-site",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "en-US,en;q=0.9"
        }
        res = self.session.post(
            f"https://{self.endpoint}/verify",
            json=payload).json()
        return res["token"]

    def __call__(self):
        inputs = self.get_inputs()
        payload = self.build_payload(inputs)
        return self.verify(payload)
