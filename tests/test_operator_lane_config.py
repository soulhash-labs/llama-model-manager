import unittest

from scripts.operator_ui_server import (
    LaneRecord,
    RoutingConfigView,
    _extract_ai_compute_config,
    _inject_ai_compute_config,
    _validate_routing_view,
)


class LaneRecordTests(unittest.TestCase):
    def test_lane_record_normalized(self) -> None:
        lane = LaneRecord(
            lane_id=" benji-core ",
            aliases=[" aurora ", "", "core", "AURORA"],
            llamacpp_url=" http://10.0.0.10:8081 ",
            ollama_url=" http://10.0.0.10:11434 ",
            enabled=1,
        ).normalized()

        self.assertEqual(lane.lane_id, "benji-core")
        self.assertEqual(lane.aliases, ["AURORA", "CORE", "AURORA"])
        self.assertEqual(lane.llamacpp_url, "http://10.0.0.10:8081")
        self.assertEqual(lane.ollama_url, "http://10.0.0.10:11434")
        self.assertTrue(lane.enabled)


class RoutingConfigViewTests(unittest.TestCase):
    def test_routing_config_view_normalized(self) -> None:
        cfg = RoutingConfigView(
            preferred_local_backend="",
            default_lane=" benji-core ",
            destination_lane_map={
                " aurora ": " benji-core ",
                " MODEL ": " worker-west ",
                "": "skip-me",
            },
            lanes=[
                LaneRecord(
                    lane_id=" benji-core ",
                    aliases=[" aurora ", "core "],
                    llamacpp_url=" http://10.0.0.10:8081 ",
                    ollama_url="",
                    enabled=True,
                ),
                LaneRecord(
                    lane_id=" worker-west ",
                    aliases=[" terran "],
                    llamacpp_url="",
                    ollama_url=" http://10.0.0.11:11434 ",
                    enabled=True,
                ),
            ],
        ).normalized()

        self.assertEqual(cfg.preferred_local_backend, "llamacpp")
        self.assertEqual(cfg.default_lane, "benji-core")
        self.assertEqual(
            cfg.destination_lane_map,
            {
                "AURORA": "benji-core",
                "MODEL": "worker-west",
            },
        )
        self.assertEqual(len(cfg.lanes), 2)
        self.assertEqual(cfg.lanes[0].lane_id, "benji-core")
        self.assertEqual(cfg.lanes[0].aliases, ["AURORA", "CORE"])
        self.assertEqual(cfg.lanes[1].lane_id, "worker-west")
        self.assertEqual(cfg.lanes[1].aliases, ["TERRAN"])


class ExtractInjectTests(unittest.TestCase):
    def test_extract_ai_compute_config_empty(self) -> None:
        cfg = _extract_ai_compute_config({})
        self.assertEqual(cfg.preferred_local_backend, "llamacpp")
        self.assertEqual(cfg.default_lane, "")
        self.assertEqual(cfg.destination_lane_map, {})
        self.assertEqual(cfg.lanes, [])

    def test_extract_ai_compute_config_dynamic_lanes(self) -> None:
        raw = {
            "ai_compute": {
                "routing": {
                    "preferred_local_backend": "ollama",
                    "default_lane": "benji-core",
                    "destination_lane_map": {
                        "AURORA": "benji-core",
                        "TERRAN": "worker-west",
                        "MODEL": "benji-core",
                    },
                },
                "lanes": {
                    "benji-core": {
                        "aliases": ["AURORA", "CORE"],
                        "llamacpp_url": "http://10.0.0.10:8081",
                        "ollama_url": "http://10.0.0.10:11434",
                        "enabled": True,
                    },
                    "worker-west": {
                        "aliases": ["TERRAN"],
                        "ollama_url": "http://10.0.0.11:11434",
                        "enabled": True,
                    },
                    "vault-node": {
                        "aliases": ["STARLIGHT"],
                        "llamacpp_url": "http://10.0.0.12:8081",
                        "enabled": False,
                    },
                },
            }
        }

        cfg = _extract_ai_compute_config(raw)

        self.assertEqual(cfg.preferred_local_backend, "ollama")
        self.assertEqual(cfg.default_lane, "benji-core")
        self.assertEqual(
            cfg.destination_lane_map,
            {
                "AURORA": "benji-core",
                "TERRAN": "worker-west",
                "MODEL": "benji-core",
            },
        )
        self.assertEqual({lane.lane_id for lane in cfg.lanes}, {"benji-core", "worker-west", "vault-node"})

        lane_map = {lane.lane_id: lane for lane in cfg.lanes}
        self.assertEqual(lane_map["benji-core"].aliases, ["AURORA", "CORE"])
        self.assertEqual(lane_map["worker-west"].ollama_url, "http://10.0.0.11:11434")
        self.assertFalse(lane_map["vault-node"].enabled)

    def test_inject_ai_compute_config_round_trip(self) -> None:
        original = {
            "meta": {"owner": "angelo"},
            "ai_compute": {
                "routing": {"preferred_local_backend": "llamacpp"},
                "lanes": {},
            },
        }

        cfg = RoutingConfigView(
            preferred_local_backend="ollama",
            default_lane="benji-core",
            destination_lane_map={
                "AURORA": "benji-core",
                "MODEL": "benji-core",
                "TERRAN": "worker-west",
            },
            lanes=[
                LaneRecord(
                    lane_id="benji-core",
                    aliases=["AURORA", "CORE"],
                    llamacpp_url="http://10.0.0.10:8081",
                    ollama_url="http://10.0.0.10:11434",
                    enabled=True,
                ),
                LaneRecord(
                    lane_id="worker-west",
                    aliases=["TERRAN"],
                    llamacpp_url="",
                    ollama_url="http://10.0.0.11:11434",
                    enabled=True,
                ),
            ],
        )

        updated = _inject_ai_compute_config(original, cfg)

        self.assertIn("meta", updated)
        self.assertEqual(updated["meta"]["owner"], "angelo")
        self.assertEqual(updated["ai_compute"]["routing"]["preferred_local_backend"], "ollama")
        self.assertEqual(updated["ai_compute"]["routing"]["default_lane"], "benji-core")
        self.assertEqual(
            updated["ai_compute"]["routing"]["destination_lane_map"],
            {
                "AURORA": "benji-core",
                "MODEL": "benji-core",
                "TERRAN": "worker-west",
            },
        )
        self.assertEqual(
            updated["ai_compute"]["lanes"]["benji-core"],
            {
                "aliases": ["AURORA", "CORE"],
                "llamacpp_url": "http://10.0.0.10:8081",
                "ollama_url": "http://10.0.0.10:11434",
                "enabled": True,
            },
        )
        self.assertEqual(
            updated["ai_compute"]["lanes"]["worker-west"]["ollama_url"],
            "http://10.0.0.11:11434",
        )

        # round-trip back through extract
        round_trip = _extract_ai_compute_config(updated)
        self.assertEqual(round_trip.preferred_local_backend, "ollama")
        self.assertEqual(round_trip.default_lane, "benji-core")
        self.assertEqual(round_trip.destination_lane_map["AURORA"], "benji-core")
        self.assertEqual({lane.lane_id for lane in round_trip.lanes}, {"benji-core", "worker-west"})


class ValidationTests(unittest.TestCase):
    def test_validate_accepts_dynamic_lane_ids(self) -> None:
        cfg = RoutingConfigView(
            preferred_local_backend="llamacpp",
            default_lane="benji-core",
            destination_lane_map={
                "AURORA": "benji-core",
                "MODEL": "worker-west",
            },
            lanes=[
                LaneRecord(
                    lane_id="benji-core",
                    aliases=["AURORA", "CORE"],
                    llamacpp_url="http://10.0.0.10:8081",
                    ollama_url="http://10.0.0.10:11434",
                    enabled=True,
                ),
                LaneRecord(
                    lane_id="worker-west",
                    aliases=["TERRAN"],
                    llamacpp_url="",
                    ollama_url="http://10.0.0.11:11434",
                    enabled=True,
                ),
            ],
        )

        _validate_routing_view(cfg)  # should not raise

    def test_validate_rejects_missing_default_lane(self) -> None:
        cfg = RoutingConfigView(
            default_lane="ghost-lane",
            lanes=[
                LaneRecord(lane_id="benji-core"),
            ],
        )

        with self.assertRaises(ValueError):
            _validate_routing_view(cfg)

    def test_validate_rejects_destination_map_to_undefined_lane(self) -> None:
        cfg = RoutingConfigView(
            default_lane="benji-core",
            destination_lane_map={"AURORA": "ghost-lane"},
            lanes=[
                LaneRecord(lane_id="benji-core"),
            ],
        )

        with self.assertRaises(ValueError):
            _validate_routing_view(cfg)

    def test_validate_rejects_duplicate_aliases_across_lanes(self) -> None:
        cfg = RoutingConfigView(
            default_lane="benji-core",
            lanes=[
                LaneRecord(lane_id="benji-core", aliases=["AURORA"]),
                LaneRecord(lane_id="worker-west", aliases=["AURORA"]),
            ],
        )

        with self.assertRaises(ValueError):
            _validate_routing_view(cfg)

    def test_validate_rejects_empty_lane_id(self) -> None:
        cfg = RoutingConfigView(
            default_lane="benji-core",
            lanes=[
                LaneRecord(lane_id=""),
            ],
        )

        with self.assertRaises(ValueError):
            _validate_routing_view(cfg)

    def test_validate_does_not_require_four_fixed_lanes(self) -> None:
        cfg = RoutingConfigView(
            preferred_local_backend="llamacpp",
            default_lane="solo-node",
            destination_lane_map={"AURORA": "solo-node"},
            lanes=[
                LaneRecord(
                    lane_id="solo-node",
                    aliases=["AURORA", "ONLY"],
                    llamacpp_url="http://10.0.0.99:8081",
                    ollama_url="",
                    enabled=True,
                ),
            ],
        )

        _validate_routing_view(cfg)  # should not raise

    def test_validate_accepts_no_default_lane_when_lanes_exist(self) -> None:
        cfg = RoutingConfigView(
            default_lane="",
            destination_lane_map={},
            lanes=[
                LaneRecord(lane_id="benji-core", aliases=["AURORA"]),
                LaneRecord(lane_id="worker-west", aliases=["TERRAN"]),
            ],
        )

        _validate_routing_view(cfg)  # should not raise


if __name__ == "__main__":
    unittest.main()
