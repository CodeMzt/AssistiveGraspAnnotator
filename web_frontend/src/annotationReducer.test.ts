import { describe, expect, it } from "vitest";
import { annotationReducer, qualityForDifficulty } from "./annotationReducer";
import type { Annotation, ClassInfo } from "./types";

const cupClass: ClassInfo = { id: 7, name: "cup", graspable: true, policy: "grasp_rect" };

function baseAnnotation(): Annotation {
  return {
    image_id: "camera_1/image.png",
    image_path: "images/camera_1/image.png",
    width: 640,
    height: 480,
    camera: "camera_1",
    source: "manual",
    split: "train",
    objects: []
  };
}

function withObjects(): Annotation {
  let annotation = annotationReducer(baseAnnotation(), {
    type: "addObject",
    classInfo: cupClass,
    bbox: [10, 20, 110, 140]
  });
  annotation = annotationReducer(annotation, {
    type: "addObject",
    classInfo: { ...cupClass, id: 9, name: "box" },
    bbox: [200, 220, 300, 340]
  });
  return annotation;
}

describe("annotationReducer", () => {
  it("adds bbox objects with the selected class", () => {
    const annotation = annotationReducer(baseAnnotation(), {
      type: "addObject",
      classInfo: cupClass,
      bbox: [10, 20, 110, 140]
    });

    expect(annotation.objects).toHaveLength(1);
    expect(annotation.objects[0]).toMatchObject({
      instance_id: 1,
      class_id: 7,
      class_name: "cup",
      bbox_xyxy: [10, 20, 110, 140],
      graspable: true,
      policy: "grasp_rect"
    });
  });

  it("deletes objects and compacts instance ids", () => {
    const annotation = annotationReducer(withObjects(), { type: "deleteObject", instanceId: 1 });

    expect(annotation.objects).toHaveLength(1);
    expect(annotation.objects[0].instance_id).toBe(1);
    expect(annotation.objects[0].class_name).toBe("box");
  });

  it("creates a four point grasp from three clicks", () => {
    const annotation = annotationReducer(withObjects(), {
      type: "addGrasp",
      instanceId: 1,
      points: [
        [20, 30],
        [80, 30],
        [80, 70]
      ]
    });

    expect(annotation.objects[0].grasps[0].points).toEqual([
      [20, 30],
      [80, 30],
      [80, 70],
      [20, 70]
    ]);
  });

  it("keeps p3 derived when editing grasp points", () => {
    let annotation = annotationReducer(withObjects(), {
      type: "addGrasp",
      instanceId: 1,
      points: [
        [20, 30],
        [80, 30],
        [80, 70]
      ]
    });

    annotation = annotationReducer(annotation, {
      type: "updateGraspPoint",
      instanceId: 1,
      graspId: 1,
      pointIndex: 1,
      point: [90, 40]
    });

    expect(annotation.objects[0].grasps[0].points).toEqual([
      [20, 30],
      [90, 40],
      [80, 70],
      [10, 60]
    ]);
  });

  it("maps difficulty changes to desktop quality defaults", () => {
    expect(qualityForDifficulty("easy")).toBe(1);
    expect(qualityForDifficulty("medium")).toBe(0.7);
    expect(qualityForDifficulty("hard")).toBe(0.4);
    expect(qualityForDifficulty("invalid")).toBe(0);

    let annotation = annotationReducer(withObjects(), {
      type: "addGrasp",
      instanceId: 1,
      points: [
        [20, 30],
        [80, 30],
        [80, 70]
      ]
    });
    annotation = annotationReducer(annotation, {
      type: "updateGraspMetadata",
      instanceId: 1,
      graspId: 1,
      difficulty: "hard"
    });

    expect(annotation.objects[0].grasps[0].quality).toBe(0.4);
  });
});
