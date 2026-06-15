import { describe, expect, it } from "vitest";
import { annotationReducer } from "./annotationReducer";
import type { Annotation, ClassInfo } from "./types";

const boxClass: ClassInfo = { id: 0, name: "phial", graspable: true };

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
    classInfo: boxClass,
    bbox: [10, 20, 110, 140]
  });
  annotation = annotationReducer(annotation, {
    type: "addObject",
    classInfo: { ...boxClass, id: 9, name: "earbud", graspable: false },
    bbox: [200, 220, 300, 340]
  });
  return annotation;
}

describe("annotationReducer", () => {
  it("adds bbox objects with default YOLO-Angle fields", () => {
    const annotation = annotationReducer(baseAnnotation(), {
      type: "addObject",
      classInfo: boxClass,
      bbox: [10, 20, 110, 140]
    });

    expect(annotation.objects).toHaveLength(1);
    expect(annotation.objects[0]).toMatchObject({
      instance_id: 1,
      class_id: 0,
      class_name: "phial",
      bbox_xyxy: [10, 20, 110, 140],
      graspable: true,
      yaw_label_status: "optional",
      occlusion_level: 0,
      difficulty: "easy",
      notes: "",
    });
  });

  it("deletes objects and compacts instance ids", () => {
    const annotation = annotationReducer(withObjects(), { type: "deleteObject", instanceId: 1 });

    expect(annotation.objects).toHaveLength(1);
    expect(annotation.objects[0].instance_id).toBe(1);
    expect(annotation.objects[0].class_name).toBe("earbud");
  });

  it("updates yaw label status", () => {
    const annotation = annotationReducer(withObjects(), {
      type: "updateObjectYawStatus",
      instanceId: 1,
      yawLabelStatus: "valid"
    });
    expect(annotation.objects[0].yaw_label_status).toBe("valid");
  });

  it("updates main axis points", () => {
    const annotation = annotationReducer(withObjects(), {
      type: "updateObjectMainAxis",
      instanceId: 1,
      mainAxisPoints: [[20, 30], [80, 30]]
    });
    expect(annotation.objects[0].main_axis_points).toEqual([[20, 30], [80, 30]]);
  });

  it("updates occlusion level", () => {
    const annotation = annotationReducer(withObjects(), {
      type: "updateObjectOcclusion",
      instanceId: 1,
      occlusionLevel: 2
    });
    expect(annotation.objects[0].occlusion_level).toBe(2);
  });

  it("updates difficulty", () => {
    const annotation = annotationReducer(withObjects(), {
      type: "updateObjectDifficulty",
      instanceId: 1,
      difficulty: "hard"
    });
    expect(annotation.objects[0].difficulty).toBe("hard");
  });

  it("updates notes", () => {
    const annotation = annotationReducer(withObjects(), {
      type: "updateObjectNotes",
      instanceId: 1,
      notes: "partially occluded"
    });
    expect(annotation.objects[0].notes).toBe("partially occluded");
  });

  it("updates template id", () => {
    const annotation = annotationReducer(withObjects(), {
      type: "updateObjectTemplate",
      instanceId: 1,
      templateId: "phial"
    });
    expect(annotation.objects[0].template_id).toBe("phial");
  });
});
