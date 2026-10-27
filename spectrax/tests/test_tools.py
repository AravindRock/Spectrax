import sys, os, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as s
S = {'vehicle': {'soc': 64, 'pos_km': 0, 'total_km': 312, 'consumption': 17.2, 'capacity_kwh': 118, 'reserve_pct': 8},
     'chargers': [{'id': 'a', 'ahead_km': 138, 'off_route_km': 2, 'kw': 350, 'available': True}, {'id': 'b', 'ahead_km': 200, 'off_route_km': 1, 'kw': 240, 'available': False}, {'id': 'c', 'ahead_km': 900, 'off_route_km': 1, 'kw': 100, 'available': True}]}
class T(unittest.TestCase):
    def test_energy(self): self.assertAlmostEqual(s.estimate_energy(S, 312)['soc_after_pct'], 64 - 312 * 17.2 / 118, 1)
    def test_ok(self): self.assertTrue(s.validate_stop(S, 'a')['accepted'])
    def test_unavailable(self): self.assertFalse(s.validate_stop(S, 'b')['accepted'])
    def test_unreachable(self): self.assertFalse(s.validate_stop(S, 'c')['accepted'])
    def test_unknown(self): self.assertFalse(s.validate_stop(S, 'zz')['accepted'])
    def test_summary(self): self.assertIn('Rain risk', s.wx_summary([{'rain_prob_6h_max': 40, 'wind_kmh': 10, 'visibility_km_min': 20, 'temp_c': 30}]))
    def test_agent_without_key(self):
        for k in ('LLM_API_KEY', 'NVIDIA_API_KEY', 'NEBIUS_API_KEY'): os.environ.pop(k, None)
        self.assertTrue(s.agent(S)['degraded'])
    def test_config_persist(self):
        import tempfile; d = tempfile.mkdtemp(); old = s.ROOT; s.ROOT = d
        try:
            s.set_config({'tavily_key': 'tvly-test-1234567890'}); self.assertIn('TAVILY_API_KEY=tvly-test-1234567890', open(os.path.join(d, '.env')).read())
        finally: s.ROOT = old; os.environ.pop('TAVILY_API_KEY', None)
    def test_config_rejects_bad_key(self): self.assertRaises(ValueError, s.set_config, {'llm_key': 'bad key!!'})
    def test_parse_json(self): self.assertEqual(s.parse_json('x {"a":1} y'), {'a': 1})
    def test_search_without_key(self):
        os.environ.pop('TAVILY_API_KEY', None); self.assertFalse(s.tavily('x')['ok'])
    # --- regression: battery drop = km x (kWh/100km) / 100 / capacity x 100  (the /100 and x100 cancel) ---
    def test_soc_drop_hand_computed(self):
        self.assertAlmostEqual(s.soc_drop_pct(138, 17.2, 118), 20.114, 2)      # 23.736 kWh of a 118 kWh pack
    def test_soc_drop_matches_kwh_path(self):
        for d in (10, 138, 312, 800): self.assertAlmostEqual(s.soc_drop_pct(d, 17.2, 118), d * 17.2 / 100 / 118 * 100, 9)
    def test_soc_drop_is_plausible(self): self.assertTrue(0 < s.soc_drop_pct(138, 17.2, 118) < 100)
    def test_rank_arrival_soc_hand_computed(self):
        r = {c['id']: c for c in s.rank_chargers(S)}; self.assertAlmostEqual(r['a']['arrival_soc_at_charger'], 64 - 20.114, 1)
    def test_unreachable_charger_is_rejected(self):
        low = {'vehicle': {**S['vehicle'], 'soc': 30}, 'chargers': [{'id': 'x', 'ahead_km': 200, 'off_route_km': 1, 'kw': 150, 'available': True}, {'id': 'y', 'ahead_km': 100, 'off_route_km': 1, 'kw': 150, 'available': True}]}
        self.assertFalse(s.validate_stop(low, 'x')['accepted'])                 # 200 km = 29.2 % -> 0.8 % left < 8 % reserve
        self.assertTrue(s.validate_stop(low, 'y')['accepted'])                  # 100 km = 14.6 % -> 15.4 % left
        self.assertFalse({c['id']: c for c in s.rank_chargers(low)}['x']['feasible'])
    def test_reserve_boundary(self):
        b = {'vehicle': S['vehicle'], 'chargers': [{'id': 'p', 'ahead_km': 384, 'off_route_km': 1, 'kw': 150, 'available': True}, {'id': 'q', 'ahead_km': 385, 'off_route_km': 1, 'kw': 150, 'available': True}]}
        f = {c['id']: c['feasible'] for c in s.rank_chargers(b)}; self.assertTrue(f['p']); self.assertFalse(f['q'])    # 8.03 % vs 7.88 % left
if __name__ == '__main__': unittest.main()
