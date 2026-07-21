import numpy as np

from app.face_recognition_service import FaceDatabase, FaceRecognitionService


def test_face_database_matches_normalized_embedding():
    db = FaceDatabase(data={"Dima": [np.array([1.0, 0.0])]})

    match = db.match(np.array([0.9, 0.1]))

    assert match.name == "Dima"
    assert match.recognized is True


def test_face_database_replaces_person_embeddings(tmp_path):
    path = tmp_path / "embeddings.pkl"
    db = FaceDatabase(path=path, data={"visitor:7": [np.array([1.0, 0.0])]})

    db.replace_person("visitor:7", [np.array([0.0, 2.0]), np.array([0.0, 3.0])])

    reloaded = FaceDatabase(path=path)
    assert len(reloaded.data["visitor:7"]) == 2
    assert np.allclose(reloaded.data["visitor:7"][0], np.array([0.0, 1.0]))


def test_face_service_uses_best_match_from_multiple_login_images(monkeypatch, tmp_path):
    class FakeFace:
        def __init__(self, embedding):
            self.bbox = np.array([0, 0, 80, 80])
            self.embedding = embedding

    class FakeApp:
        calls = 0

        def get(self, _frame):
            self.calls += 1
            if self.calls == 1:
                return [FakeFace(np.array([0.2, 0.8]))]
            return [FakeFace(np.array([1.0, 0.0]))]

    class FakeCv2:
        IMREAD_COLOR = 1

        @staticmethod
        def imdecode(_image_array, _mode):
            return np.zeros((80, 80, 3), dtype=np.uint8)

    monkeypatch.setitem(__import__("sys").modules, "cv2", FakeCv2)

    db = FaceDatabase(path=tmp_path / "embeddings.pkl", data={"visitor:7": [np.array([1.0, 0.0])]})
    service = FaceRecognitionService(database=db)
    service._app = FakeApp()

    match = service.recognize_images_base64(["AAAA", "AAAA"])

    assert match.name == "visitor:7"
    assert match.recognized is True


def test_face_service_stops_after_confident_login_match(monkeypatch, tmp_path):
    class FakeFace:
        def __init__(self, embedding):
            self.bbox = np.array([0, 0, 80, 80])
            self.embedding = embedding

    class FakeApp:
        calls = 0

        def get(self, _frame):
            self.calls += 1
            return [FakeFace(np.array([1.0, 0.0]))]

    class FakeCv2:
        IMREAD_COLOR = 1

        @staticmethod
        def imdecode(_image_array, _mode):
            return np.zeros((80, 80, 3), dtype=np.uint8)

    monkeypatch.setitem(__import__("sys").modules, "cv2", FakeCv2)

    db = FaceDatabase(path=tmp_path / "embeddings.pkl", data={"visitor:7": [np.array([1.0, 0.0])]})
    service = FaceRecognitionService(database=db)
    fake_app = FakeApp()
    service._app = fake_app

    match = service.recognize_images_base64(["AAAA", "AAAA", "AAAA"])

    assert match.name == "visitor:7"
    assert match.recognized is True
    assert fake_app.calls == 1


def test_face_service_enrolls_multiple_base64_images(monkeypatch, tmp_path):
    class FakeFace:
        def __init__(self, value):
            self.bbox = np.array([0, 0, 80, 80])
            self.embedding = np.array([float(value), 0.0])

    class FakeApp:
        calls = 0

        def get(self, _frame):
            self.calls += 1
            return [FakeFace(self.calls)]

    class FakeCv2:
        IMREAD_COLOR = 1

        @staticmethod
        def imdecode(_image_array, _mode):
            return np.zeros((80, 80, 3), dtype=np.uint8)

    monkeypatch.setitem(__import__("sys").modules, "cv2", FakeCv2)

    db = FaceDatabase(path=tmp_path / "embeddings.pkl", data={})
    service = FaceRecognitionService(database=db)
    service._app = FakeApp()

    count = service.enroll_images("visitor:7", ["data:image/jpeg;base64,AAAA", "AAAA", "AAAA"])

    assert count == 3
    assert len(FaceDatabase(path=db.path).data["visitor:7"]) == 3
