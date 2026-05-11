import unittest


from backend.main import MAX_GLOBAL_GENERATIONS, _can_accept_generation


class GenerationCapacityTest(unittest.TestCase):
    def test_can_accept_generation_allows_capacity_below_global_limit(self):
        active = {str(i): {} for i in range(MAX_GLOBAL_GENERATIONS - 1)}

        self.assertTrue(_can_accept_generation(active))

    def test_can_accept_generation_rejects_at_global_limit(self):
        active = {str(i): {} for i in range(MAX_GLOBAL_GENERATIONS)}

        self.assertFalse(_can_accept_generation(active))


if __name__ == "__main__":
    unittest.main()
