from weather import compass


class TestCompass:
    def test_north(self):
        assert compass(0) == "N"
        assert compass(360) == "N"

    def test_northeast(self):
        assert compass(45) == "NE"

    def test_east(self):
        assert compass(90) == "E"

    def test_south(self):
        assert compass(180) == "S"

    def test_southwest(self):
        assert compass(225) == "SW"
