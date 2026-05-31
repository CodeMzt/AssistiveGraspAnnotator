import { describe, expect, it } from "vitest";
import { hitTest } from "./geometry";
import type { Annotation } from "./types";

function annotation(): Annotation {
  return {
    image_id: "camera_1/image.png",
    image_path: "images/camera_1/image.png",
    width: 640,
    height: 480,
    camera: "camera_1",
    source: "manual",
    split: "train",
    objects: [
      {
        instance_id: 1,
        class_id: 0,
        class_name: "object",
        bbox_xyxy: [100, 100, 300, 260],
        graspable: true,
        policy: "grasp_rect",
        grasps: [
          {
            grasp_id: 1,
            points: [
              [140, 140],
              [220, 140],
              [220, 190],
              [140, 190]
            ],
            axis_convention: "p0_to_p1_is_grasp_width_axis",
            quality: 1,
            difficulty: "easy",
            note: ""
          }
        ]
      }
    ]
  };
}

describe("hitTest", () => {
  it("prioritizes grasps over bbox body hits", () => {
    expect(hitTest(annotation(), [170, 160], 12)).toEqual({
      objectId: 1,
      graspId: 1,
      handle: "body"
    });
  });

  it("hits bbox handles before bbox body", () => {
    expect(hitTest(annotation(), [100, 100], 12)).toEqual({
      objectId: 1,
      graspId: null,
      handle: "nw"
    });
  });

  it("hits bbox body and empty space", () => {
    expect(hitTest(annotation(), [280, 240], 12)).toEqual({
      objectId: 1,
      graspId: null,
      handle: "body"
    });
    expect(hitTest(annotation(), [20, 20], 12)).toEqual({
      objectId: null,
      graspId: null,
      handle: null
    });
  });
});
