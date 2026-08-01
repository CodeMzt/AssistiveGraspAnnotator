from __future__ import annotations

import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from io import BytesIO

import yaml
from PIL import Image

from assistive_grasp_annotator.web.config import WebConfig, resolve_allowed_path
from assistive_grasp_annotator.web.datasets import DatasetError, DatasetService, DatasetValidationError
from assistive_grasp_annotator.web.ids import decode_image_id, encode_image_id
from assistive_grasp_annotator.web.state import StateStore
from assistive_grasp_annotator.tools.audit_annotations import audit_annotations
from assistive_grasp_annotator.tools.migrate_new_dataset import migrate_dataset


def make_dataset(root: Path) -> Path:
    images_dir = root / "images" / "camera_1"
    images_dir.mkdir(parents=True)
    (root / "annotations").mkdir()
    (root / "splits").mkdir()
    (root / "generated").mkdir()
    Image.new("RGB", (80, 60), (120, 80, 40)).save(images_dir / "000001.jpg")
    with open(root / "classes.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(
            {"classes": [{"id": 0, "name": "phone", "graspable": True}]},
            f,
            sort_keys=False,
        )
    return root


def sample_annotation() -> dict:
    return {
        "image_id": "000001",
        "image_path": "",
        "width": 80,
        "height": 60,
        "camera": "camera_1",
        "source": "",
        "split": "train",
        "objects": [
            {
                "instance_id": 1,
                "class_id": 0,
                "class_name": "phone",
                "bbox_xyxy": [10, 10, 50, 40],
                "graspable": True,
                "template_id": "phone",
                "yaw_label_status": "valid",
                "occlusion_level": 0,
                "difficulty": "easy",
                "main_axis_points": [[20, 20], [40, 20]],
                "notes": "",
            }
        ],
    }


def invalid_intermediate_annotation() -> dict:
    data = sample_annotation()
    data["objects"][0]["bbox_xyxy"] = [50, 40, 10, 10]
    data["objects"][0]["yaw_label_status"] = "invalid_status"
    return data


def warning_annotation() -> dict:
    data = sample_annotation()
    data["objects"][0]["class_id"] = 1
    data["objects"][0]["class_name"] = "phone_other"
    data["objects"][0]["graspable"] = True
    data["objects"][0]["yaw_label_status"] = "optional"
    return data


class WebBackendTests(unittest.TestCase):
    def test_image_id_roundtrip(self):
        key = "camera_1/nested image 01.jpg"
        self.assertEqual(decode_image_id(encode_image_id(key)), key)

    def test_allowed_path_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.assertEqual(resolve_allowed_path(root, [root]), root)
            with self.assertRaises(ValueError):
                resolve_allowed_path(root.parent, [root / "datasets"])

    def test_dataset_annotation_roundtrip_and_etag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_dataset(Path(tmp) / "dataset")
            config = WebConfig(
                dataset_roots=[root.parent.resolve()],
                upload_root=(Path(tmp) / "uploads").resolve(),
                state_db=(Path(tmp) / "state.sqlite3").resolve(),
                lock_ttl_seconds=60,
                frontend_dist=(Path(tmp) / "dist").resolve(),
            )
            store = StateStore(config.state_db)
            service = DatasetService(config, store)
            meta = service.open_dataset(root)
            _, dataset = service.get_dataset(meta["dataset_id"])
            entry = dataset.list_images()[0]
            payload = dataset.annotation_payload(entry.image_id)
            self.assertEqual(payload["etag"], "missing")

            saved = dataset.save_annotation(entry.image_id, sample_annotation(), payload["etag"])
            self.assertTrue(saved["validation"]["valid"])
            self.assertNotEqual(saved["etag"], "missing")
            self.assertEqual(saved["annotation"]["objects"][0]["class_name"], "phone")
            audit = audit_annotations(root)
            self.assertEqual(audit["annotation_count"], 1)
            self.assertEqual(audit["error_count"], 0)

            with self.assertRaises(DatasetError):
                dataset.save_annotation(entry.image_id, sample_annotation(), "missing")

    def test_dataset_library_create_rename_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = (Path(tmp) / "datasets").resolve()
            config = WebConfig(
                dataset_roots=[library],
                upload_root=library,
                state_db=(Path(tmp) / "state.sqlite3").resolve(),
                lock_ttl_seconds=60,
                frontend_dist=(Path(tmp) / "dist").resolve(),
            )
            store = StateStore(config.state_db)
            service = DatasetService(config, store)
            created = service.create_dataset(
                "Bench Set",
                classes=[{"id": 0, "name": "phone", "graspable": True}],
            )
            dataset_id = created["dataset_id"]
            root = Path(created["root"])
            self.assertEqual(created["name"], "Bench Set")
            self.assertTrue((root / "images" / "camera_1").is_dir())
            self.assertTrue((root / "classes.yaml").exists())

            renamed = service.rename_dataset(dataset_id, "Renamed Set")
            self.assertEqual(renamed["name"], "Renamed Set")
            self.assertEqual(Path(renamed["root"]), root)

            listed = service.list_datasets()
            self.assertEqual(listed[0]["name"], "Renamed Set")

            deleted = service.delete_dataset(dataset_id)
            self.assertFalse(root.exists())
            self.assertTrue(Path(deleted["trash_path"]).exists())
            self.assertEqual(service.list_datasets(), [])

    def test_dataset_library_discovers_existing_fixed_root_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = (Path(tmp) / "datasets").resolve()
            existing = make_dataset(library / "existing_case")
            config = WebConfig(
                dataset_roots=[library],
                upload_root=library,
                state_db=(Path(tmp) / "state.sqlite3").resolve(),
                lock_ttl_seconds=60,
                frontend_dist=(Path(tmp) / "dist").resolve(),
            )
            service = DatasetService(config, StateStore(config.state_db))
            listed = service.list_datasets()
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["name"], "existing_case")
            self.assertEqual(Path(listed[0]["root"]), existing)

    def test_save_invalid_annotation_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_dataset(Path(tmp) / "dataset")
            config = WebConfig(
                dataset_roots=[root.parent.resolve()],
                upload_root=(Path(tmp) / "uploads").resolve(),
                state_db=(Path(tmp) / "state.sqlite3").resolve(),
                lock_ttl_seconds=60,
                frontend_dist=(Path(tmp) / "dist").resolve(),
            )
            store = StateStore(config.state_db)
            service = DatasetService(config, store)
            meta = service.open_dataset(root)
            _, dataset = service.get_dataset(meta["dataset_id"])
            entry = dataset.list_images()[0]
            payload = dataset.annotation_payload(entry.image_id)

            with self.assertRaises(DatasetValidationError) as raised:
                dataset.save_annotation(entry.image_id, invalid_intermediate_annotation(), payload["etag"])
            self.assertGreaterEqual(len(raised.exception.validation["errors"]), 1)
            self.assertFalse((root / "annotations" / "camera_1" / "000001.json").exists())

    def test_locks_exclude_other_users(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.sqlite3")
            ok, alice = store.acquire_lock("ds", "img", "camera/000001.jpg", "alice", 60)
            self.assertTrue(ok)
            ok, held = store.acquire_lock("ds", "img", "camera/000001.jpg", "bob", 60)
            self.assertFalse(ok)
            self.assertEqual(held.user, "alice")
            self.assertTrue(store.verify_lock("ds", "img", alice.id, alice.token, "alice"))
            refreshed = store.heartbeat_lock(alice.id, alice.token, "alice", 60)
            self.assertIsNotNone(refreshed)
            self.assertTrue(store.release_lock(alice.id, alice.token, "alice"))
            ok, bob = store.acquire_lock("ds", "img", "camera/000001.jpg", "bob", 60)
            self.assertTrue(ok)
            self.assertEqual(bob.user, "bob")


class WebApiTests(unittest.TestCase):
    def test_api_accepts_header_auth_without_cookie(self):
        try:
            from fastapi.testclient import TestClient
            from assistive_grasp_annotator.web.app import create_app
        except Exception as exc:  # pragma: no cover - optional runtime dependency in minimal envs
            self.skipTest(f"FastAPI test dependencies unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = make_dataset(Path(tmp) / "dataset")
            config = WebConfig(
                dataset_roots=[root.parent.resolve()],
                upload_root=(Path(tmp) / "uploads").resolve(),
                state_db=(Path(tmp) / "state.sqlite3").resolve(),
                lock_ttl_seconds=60,
                frontend_dist=(Path(tmp) / "dist").resolve(),
            )
            client = TestClient(create_app(config))
            protected = client.post("/api/datasets/open", json={"path": str(root)})
            self.assertEqual(protected.status_code, 401)

            headers = {"X-AGA-User": "lan%20user"}
            opened = client.post("/api/datasets/open", json={"path": str(root)}, headers=headers)
            self.assertEqual(opened.status_code, 200, opened.text)
            dataset_id = opened.json()["dataset_id"]
            image_id = client.get(f"/api/datasets/{dataset_id}/images").json()["items"][0]["image_id"]

            lock = client.post(f"/api/datasets/{dataset_id}/images/{image_id}/lock", headers=headers)
            self.assertEqual(lock.status_code, 200, lock.text)
            self.assertEqual(lock.json()["user"], "lan user")

    def test_api_edit_flow(self):
        try:
            from fastapi.testclient import TestClient
            from assistive_grasp_annotator.web.app import create_app
        except Exception as exc:  # pragma: no cover - optional runtime dependency in minimal envs
            self.skipTest(f"FastAPI test dependencies unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = make_dataset(Path(tmp) / "dataset")
            config = WebConfig(
                dataset_roots=[root.parent.resolve()],
                upload_root=(Path(tmp) / "uploads").resolve(),
                state_db=(Path(tmp) / "state.sqlite3").resolve(),
                lock_ttl_seconds=60,
                frontend_dist=(Path(tmp) / "dist").resolve(),
            )
            client = TestClient(create_app(config))
            self.assertEqual(client.post("/api/login", json={"username": "alice"}).status_code, 200)
            opened = client.post("/api/datasets/open", json={"path": str(root)})
            self.assertEqual(opened.status_code, 200, opened.text)
            dataset_id = opened.json()["dataset_id"]

            images = client.get(f"/api/datasets/{dataset_id}/images").json()["items"]
            image_id = images[0]["image_id"]
            ann_payload = client.get(f"/api/datasets/{dataset_id}/images/{image_id}/annotation").json()
            lock = client.post(f"/api/datasets/{dataset_id}/images/{image_id}/lock")
            self.assertEqual(lock.status_code, 200, lock.text)
            lock_payload = lock.json()

            save = client.put(
                f"/api/datasets/{dataset_id}/images/{image_id}/annotation",
                json={
                    "lock_id": lock_payload["lock_id"],
                    "lock_token": lock_payload["lock_token"],
                    "etag": ann_payload["etag"],
                    "annotation": sample_annotation(),
                },
            )
            self.assertEqual(save.status_code, 200, save.text)
            self.assertTrue((root / "annotations" / "camera_1" / "000001.json").exists())
            stats = client.get(f"/api/datasets/{dataset_id}/stats")
            self.assertEqual(stats.status_code, 200, stats.text)
            self.assertEqual(stats.json()["dataset"]["image_count"], 1)
            self.assertEqual(stats.json()["dataset"]["object_count"], 1)
            self.assertEqual(stats.json()["classes"][0]["axis_count"], 1)

    def test_mask_candidate_and_review_flow(self):
        try:
            from fastapi.testclient import TestClient
            from assistive_grasp_annotator.web.app import create_app
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"FastAPI test dependencies unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = make_dataset(Path(tmp) / "dataset")
            config = WebConfig(
                dataset_roots=[root.parent.resolve()],
                upload_root=(Path(tmp) / "uploads").resolve(),
                state_db=(Path(tmp) / "state.sqlite3").resolve(),
                lock_ttl_seconds=60,
                frontend_dist=(Path(tmp) / "dist").resolve(),
            )
            client = TestClient(create_app(config))
            client.post("/api/login", json={"username": "alice"})
            dataset_id = client.post("/api/datasets/open", json={"path": str(root)}).json()["dataset_id"]
            image_id = client.get(f"/api/datasets/{dataset_id}/images").json()["items"][0]["image_id"]
            ann_payload = client.get(f"/api/datasets/{dataset_id}/images/{image_id}/annotation").json()
            lock = client.post(f"/api/datasets/{dataset_id}/images/{image_id}/lock").json()
            save = client.put(
                f"/api/datasets/{dataset_id}/images/{image_id}/annotation",
                json={
                    "lock_id": lock["lock_id"],
                    "lock_token": lock["lock_token"],
                    "etag": ann_payload["etag"],
                    "annotation": sample_annotation(),
                },
            )
            self.assertEqual(save.status_code, 200, save.text)

            with mock.patch.dict("os.environ", {"AGA_MASK_TEACHER_MODE": "fake"}):
                candidate = client.post(f"/api/datasets/{dataset_id}/images/{image_id}/objects/1/mask-candidate")
            self.assertEqual(candidate.status_code, 200, candidate.text)
            body = candidate.json()
            self.assertEqual(body["schema_version"], "mask_candidate_v1")
            self.assertGreater(len(body["smooth_contour_px"]), 32)
            self.assertTrue((root / "generated" / "mask_candidates").exists())

            preview = client.get(f"/api/datasets/{dataset_id}/images/{image_id}/objects/1/mask-candidate/preview")
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual(preview.headers["content-type"], "image/png")

            review = client.put(
                f"/api/datasets/{dataset_id}/images/{image_id}/objects/1/mask-review",
                json={"candidate_id": body["candidate_id"], "score": 2, "failure_tags": ["edge_miss"], "notes": "usable"},
            )
            self.assertEqual(review.status_code, 200, review.text)
            self.assertEqual(review.json()["review_status"], "usable")
            mask_payload = client.get(f"/api/datasets/{dataset_id}/images/{image_id}/mask-review")
            self.assertEqual(mask_payload.status_code, 200, mask_payload.text)
            self.assertEqual(mask_payload.json()["objects"][0]["review"]["score"], 2)

    def test_new_dataset_migration_canonicalizes_legacy_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "new_dataset"
            images_dir = root / "images" / "camera_1"
            ann_dir = root / "annotations" / "camera_1"
            images_dir.mkdir(parents=True)
            ann_dir.mkdir(parents=True)
            (root / "splits").mkdir()
            (root / "generated").mkdir()
            Image.new("RGB", (80, 60), (120, 80, 40)).save(images_dir / "000001.jpg")
            with open(root / "classes.yaml", "w", encoding="utf-8") as f:
                yaml.safe_dump(
                    {"classes": [{"id": 0, "name": "earbud", "graspable": True}]},
                    f,
                    sort_keys=False,
                )
            ann = sample_annotation()
            ann["objects"][0]["class_id"] = 0
            ann["objects"][0]["class_name"] = "earbud" + "_" + "A"
            ann["objects"][0]["yaw_label_status"] = "optional"
            (ann_dir / "000001.json").write_text(json.dumps(ann), encoding="utf-8")

            dry_run = migrate_dataset(root, apply=False)
            self.assertEqual(dry_run["changed_files"], 1)
            self.assertEqual(json.loads((ann_dir / "000001.json").read_text(encoding="utf-8"))["objects"][0]["class_name"], "earbud" + "_" + "A")

            applied = migrate_dataset(root, apply=True)
            self.assertEqual(applied["legacy_class_name_count"], 1)
            migrated = json.loads((ann_dir / "000001.json").read_text(encoding="utf-8"))
            self.assertEqual(migrated["objects"][0]["class_name"], "earbud")
            self.assertEqual(migrated["objects"][0]["yaw_label_status"], "valid")
            second = migrate_dataset(root, apply=False)
            self.assertEqual(second["changed_files"], 0)

    def test_api_dataset_library_flow(self):
        try:
            from fastapi.testclient import TestClient
            from assistive_grasp_annotator.web.app import create_app
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"FastAPI test dependencies unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            library = (Path(tmp) / "datasets").resolve()
            config = WebConfig(
                dataset_roots=[library],
                upload_root=library,
                state_db=(Path(tmp) / "state.sqlite3").resolve(),
                lock_ttl_seconds=60,
                frontend_dist=(Path(tmp) / "dist").resolve(),
            )
            client = TestClient(create_app(config))
            client.post("/api/login", json={"username": "alice"})

            created = client.post(
                "/api/datasets",
                json={
                    "name": "Library Case",
                    "classes": [{"id": 0, "name": "phone", "graspable": True}],
                },
            )
            self.assertEqual(created.status_code, 200, created.text)
            dataset_id = created.json()["dataset_id"]
            self.assertEqual(created.json()["name"], "Library Case")

            listed = client.get("/api/datasets")
            self.assertEqual(listed.status_code, 200, listed.text)
            self.assertEqual(listed.json()["datasets"][0]["name"], "Library Case")

            renamed = client.patch(f"/api/datasets/{dataset_id}", json={"name": "Library Renamed"})
            self.assertEqual(renamed.status_code, 200, renamed.text)
            self.assertEqual(renamed.json()["name"], "Library Renamed")

            deleted = client.delete(f"/api/datasets/{dataset_id}")
            self.assertEqual(deleted.status_code, 200, deleted.text)
            self.assertTrue(Path(deleted.json()["deleted"]["trash_path"]).exists())
            self.assertEqual(client.get("/api/datasets").json()["datasets"], [])

    def test_api_validate_warnings_and_upload_dataset(self):
        try:
            from fastapi.testclient import TestClient
            from assistive_grasp_annotator.web.app import create_app
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"FastAPI test dependencies unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = make_dataset(Path(tmp) / "dataset")
            with open(root / "classes.yaml", "w", encoding="utf-8") as f:
                yaml.safe_dump(
                    {
                        "classes": [
                            {"id": 0, "name": "phone", "graspable": True},
                            {"id": 1, "name": "remote", "graspable": False},
                        ]
                    },
                    f,
                    sort_keys=False,
                )
            config = WebConfig(
                dataset_roots=[root.parent.resolve()],
                upload_root=(Path(tmp) / "uploads").resolve(),
                state_db=(Path(tmp) / "state.sqlite3").resolve(),
                lock_ttl_seconds=60,
                frontend_dist=(Path(tmp) / "dist").resolve(),
            )
            client = TestClient(create_app(config))
            client.post("/api/login", json={"username": "alice"})
            opened = client.post("/api/datasets/open", json={"path": str(root)})
            dataset_id = opened.json()["dataset_id"]
            image_id = client.get(f"/api/datasets/{dataset_id}/images").json()["items"][0]["image_id"]
            ann_payload = client.get(f"/api/datasets/{dataset_id}/images/{image_id}/annotation").json()
            lock = client.post(f"/api/datasets/{dataset_id}/images/{image_id}/lock").json()
            save = client.put(
                f"/api/datasets/{dataset_id}/images/{image_id}/annotation",
                json={
                    "lock_id": lock["lock_id"],
                    "lock_token": lock["lock_token"],
                    "etag": ann_payload["etag"],
                    "annotation": warning_annotation(),
                },
            )
            self.assertEqual(save.status_code, 200, save.text)
            validate = client.post(f"/api/datasets/{dataset_id}/validate", json={"image_id": image_id})
            self.assertEqual(validate.status_code, 200, validate.text)
            self.assertTrue(validate.json()["valid"])
            self.assertEqual(len(validate.json()["warnings"]), 1)

            upload_image = BytesIO()
            Image.new("RGB", (32, 24), (1, 2, 3)).save(upload_image, format="PNG")
            upload_image.seek(0)
            uploaded = client.post(
                "/api/datasets/upload",
                data={
                    "name": "upload_case",
                    "camera_name": "cam_a",
                    "upload_batch_id": "new-batch-1",
                    "classes_json": json.dumps([{"id": 0, "name": "phone", "graspable": True}]),
                },
                files={"files": ("one.png", upload_image, "image/png")},
            )
            self.assertEqual(uploaded.status_code, 200, uploaded.text)
            upload_root = Path(uploaded.json()["root"])
            self.assertTrue((upload_root / "images" / "cam_a" / "000001.png").exists())
            self.assertTrue((upload_root / "annotations").is_dir())
            self.assertTrue((upload_root / "classes.yaml").exists())

            repeated_upload_image = BytesIO()
            Image.new("RGB", (32, 24), (1, 2, 3)).save(repeated_upload_image, format="PNG")
            repeated_upload_image.seek(0)
            repeated_upload = client.post(
                "/api/datasets/upload",
                data={
                    "name": "upload_case",
                    "camera_name": "cam_a",
                    "upload_batch_id": "new-batch-1",
                    "classes_json": json.dumps([{"id": 0, "name": "phone", "graspable": True}]),
                },
                files={"files": ("one.png", repeated_upload_image, "image/png")},
            )
            self.assertEqual(repeated_upload.status_code, 200, repeated_upload.text)
            self.assertEqual(repeated_upload.json()["dataset_id"], uploaded.json()["dataset_id"])
            self.assertEqual(repeated_upload.json()["image_count"], 1)
            self.assertFalse((upload_root.parent / "upload_case_2").exists())

            chunked_new_image = BytesIO()
            Image.new("RGB", (30, 20), (4, 5, 6)).save(chunked_new_image, format="PNG")
            chunked_new_bytes = chunked_new_image.getvalue()
            chunk = client.post(
                "/api/uploads/chunk",
                data={
                    "session_id": "session-new-dataset",
                    "file_id": "file-new",
                    "filename": "new_chunked.png",
                    "chunk_index": "0",
                    "total_chunks": "1",
                },
                files={"chunk": ("chunk.part", BytesIO(chunked_new_bytes), "application/octet-stream")},
            )
            self.assertEqual(chunk.status_code, 200, chunk.text)
            chunked_dataset = client.post(
                "/api/datasets/upload-chunked/complete",
                json={
                    "session_id": "session-new-dataset",
                    "upload_batch_id": "new-chunked-batch-1",
                    "name": "chunked_upload_case",
                    "camera_name": "cam_b",
                    "classes": [{"id": 0, "name": "phone", "graspable": True}],
                    "files": [{"file_id": "file-new", "filename": "new_chunked.png", "size": len(chunked_new_bytes)}],
                },
            )
            self.assertEqual(chunked_dataset.status_code, 200, chunked_dataset.text)
            chunked_root = Path(chunked_dataset.json()["root"])
            self.assertTrue((chunked_root / "images" / "cam_b" / "000001.png").exists())

    def test_api_update_classes_writes_classes_yaml(self):
        try:
            from fastapi.testclient import TestClient
            from assistive_grasp_annotator.web.app import create_app
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"FastAPI test dependencies unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = make_dataset(Path(tmp) / "dataset")
            config = WebConfig(
                dataset_roots=[root.parent.resolve()],
                upload_root=(Path(tmp) / "uploads").resolve(),
                state_db=(Path(tmp) / "state.sqlite3").resolve(),
                lock_ttl_seconds=60,
                frontend_dist=(Path(tmp) / "dist").resolve(),
            )
            client = TestClient(create_app(config))
            client.post("/api/login", json={"username": "alice"})
            dataset_id = client.post("/api/datasets/open", json={"path": str(root)}).json()["dataset_id"]

            updated = client.put(
                f"/api/datasets/{dataset_id}/classes",
                json={
                    "classes": [
                        {"id": 0, "name": "phone", "graspable": True},
                        {"id": 1, "name": "remote", "graspable": True},
                    ]
                },
            )
            self.assertEqual(updated.status_code, 200, updated.text)
            self.assertEqual(updated.json()["classes"][1]["name"], "remote")
            with open(root / "classes.yaml", "r", encoding="utf-8") as f:
                saved = yaml.safe_load(f)
            self.assertEqual(saved["classes"][0]["name"], "phone")

            duplicate = client.put(
                f"/api/datasets/{dataset_id}/classes",
                json={
                    "classes": [
                        {"id": 0, "name": "phone", "graspable": True},
                        {"id": 0, "name": "remote", "graspable": True},
                    ]
                },
            )
            self.assertEqual(duplicate.status_code, 400)

    def test_api_delete_image_moves_image_and_annotation_to_trash(self):
        try:
            from fastapi.testclient import TestClient
            from assistive_grasp_annotator.web.app import create_app
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"FastAPI test dependencies unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = make_dataset(Path(tmp) / "dataset")
            config = WebConfig(
                dataset_roots=[root.parent.resolve()],
                upload_root=(Path(tmp) / "uploads").resolve(),
                state_db=(Path(tmp) / "state.sqlite3").resolve(),
                lock_ttl_seconds=60,
                frontend_dist=(Path(tmp) / "dist").resolve(),
            )
            client = TestClient(create_app(config))
            client.post("/api/login", json={"username": "alice"})
            dataset_id = client.post("/api/datasets/open", json={"path": str(root)}).json()["dataset_id"]
            image_id = client.get(f"/api/datasets/{dataset_id}/images").json()["items"][0]["image_id"]
            ann_payload = client.get(f"/api/datasets/{dataset_id}/images/{image_id}/annotation").json()
            lock = client.post(f"/api/datasets/{dataset_id}/images/{image_id}/lock").json()
            save = client.put(
                f"/api/datasets/{dataset_id}/images/{image_id}/annotation",
                json={
                    "lock_id": lock["lock_id"],
                    "lock_token": lock["lock_token"],
                    "etag": ann_payload["etag"],
                    "annotation": sample_annotation(),
                },
            )
            self.assertEqual(save.status_code, 200, save.text)

            deleted = client.delete(f"/api/datasets/{dataset_id}/images/{image_id}")
            self.assertEqual(deleted.status_code, 200, deleted.text)
            self.assertFalse((root / "images" / "camera_1" / "000001.jpg").exists())
            self.assertFalse((root / "annotations" / "camera_1" / "000001.json").exists())
            self.assertTrue(Path(deleted.json()["deleted"]["trash_image_path"]).exists())
            self.assertTrue(Path(deleted.json()["deleted"]["trash_annotation_path"]).exists())
            self.assertEqual(client.get(f"/api/datasets/{dataset_id}/images").json()["items"], [])

    def test_api_upload_images_to_existing_dataset(self):
        try:
            from fastapi.testclient import TestClient
            from assistive_grasp_annotator.web.app import create_app
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"FastAPI test dependencies unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = make_dataset(Path(tmp) / "dataset")
            config = WebConfig(
                dataset_roots=[root.parent.resolve()],
                upload_root=(Path(tmp) / "uploads").resolve(),
                state_db=(Path(tmp) / "state.sqlite3").resolve(),
                lock_ttl_seconds=60,
                frontend_dist=(Path(tmp) / "dist").resolve(),
            )
            client = TestClient(create_app(config))
            client.post("/api/login", json={"username": "alice"})
            dataset_id = client.post("/api/datasets/open", json={"path": str(root)}).json()["dataset_id"]

            upload_image = BytesIO()
            Image.new("RGB", (24, 18), (8, 9, 10)).save(upload_image, format="PNG")
            upload_image.seek(0)
            uploaded = client.post(
                f"/api/datasets/{dataset_id}/images/upload",
                data={"upload_batch_id": "batch-1"},
                files={"files": ("extra.png", upload_image, "image/png")},
            )
            self.assertEqual(uploaded.status_code, 200, uploaded.text)
            self.assertEqual(uploaded.json()["added"], 1)
            self.assertEqual(uploaded.json()["dataset"]["image_count"], 2)
            self.assertTrue((root / "images" / "camera_1" / "000002.png").exists())

            repeated_image = BytesIO()
            Image.new("RGB", (24, 18), (8, 9, 10)).save(repeated_image, format="PNG")
            repeated_image.seek(0)
            repeated = client.post(
                f"/api/datasets/{dataset_id}/images/upload",
                data={"upload_batch_id": "batch-1"},
                files={"files": ("extra.png", repeated_image, "image/png")},
            )
            self.assertEqual(repeated.status_code, 200, repeated.text)
            self.assertEqual(repeated.json()["added"], 1)
            self.assertEqual(repeated.json()["dataset"]["image_count"], 2)
            self.assertFalse((root / "images" / "camera_1" / "000003.png").exists())

            chunked_image = BytesIO()
            Image.new("RGB", (28, 22), (11, 12, 13)).save(chunked_image, format="PNG")
            chunked_bytes = chunked_image.getvalue()
            midpoint = max(1, len(chunked_bytes) // 2)
            for index, payload in enumerate([chunked_bytes[:midpoint], chunked_bytes[midpoint:]]):
                chunk = client.post(
                    "/api/uploads/chunk",
                    data={
                        "session_id": "session-existing",
                        "file_id": "file-a",
                        "filename": "chunked.png",
                        "chunk_index": str(index),
                        "total_chunks": "2",
                    },
                    files={"chunk": ("chunk.part", BytesIO(payload), "application/octet-stream")},
                )
                self.assertEqual(chunk.status_code, 200, chunk.text)

            chunked_complete = client.post(
                f"/api/datasets/{dataset_id}/images/upload-chunked/complete",
                json={
                    "session_id": "session-existing",
                    "upload_batch_id": "chunked-batch-1",
                    "files": [{"file_id": "file-a", "filename": "chunked.png", "size": len(chunked_bytes)}],
                },
            )
            self.assertEqual(chunked_complete.status_code, 200, chunked_complete.text)
            self.assertEqual(chunked_complete.json()["added"], 1)
            self.assertEqual(chunked_complete.json()["dataset"]["image_count"], 3)
            self.assertTrue((root / "images" / "camera_1" / "000003.png").exists())

            chunked_repeat = client.post(
                f"/api/datasets/{dataset_id}/images/upload-chunked/complete",
                json={
                    "session_id": "session-existing",
                    "upload_batch_id": "chunked-batch-1",
                    "files": [{"file_id": "file-a", "filename": "chunked.png", "size": len(chunked_bytes)}],
                },
            )
            self.assertEqual(chunked_repeat.status_code, 200, chunked_repeat.text)
            self.assertEqual(chunked_repeat.json()["dataset"]["image_count"], 3)
            self.assertFalse((root / "images" / "camera_1" / "000004.png").exists())


if __name__ == "__main__":
    unittest.main()
