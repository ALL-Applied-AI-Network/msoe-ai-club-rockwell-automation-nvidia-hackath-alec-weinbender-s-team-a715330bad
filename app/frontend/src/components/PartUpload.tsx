import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrapAs, type Schemas } from "../backend/client";
import { Button } from "./Button";
import { FileDrop } from "./FileDrop";
import styles from "./PartUpload.module.css";

type Part = Schemas["PartResponse"];
type Units = "mm" | "in";

/** Uploads a part's CAD file: the Parts page, and the wizard's step 1. A STEP carries its own units; an STL doesn't, so
 *  it asks millimetres or inches before sending one. The API's message shows when it refuses a file (a SolidWorks file,
 *  one it can't read). */
export function PartUpload({ onUploaded }: { onUploaded: (part: Part) => void }) {
  const queryClient = useQueryClient();
  const [stl, setStl] = useState<File | null>(null); // an STL waiting for its units
  const upload = useMutation({
    mutationFn: ({ file, units }: { file: File; units?: Units }) =>
      unwrapAs<Part>(
        api.POST("/api/parts", {
          // The schema calls the file a string; it's sent as multipart form data.
          body: { part_file: file as unknown as string, units },
          bodySerializer: (body) => {
            const form = new FormData();
            form.append("part_file", body.part_file as unknown as File);
            if (body.units) form.append("units", body.units);
            return form;
          },
        }),
      ),
    onSuccess: (part) => {
      setStl(null);
      void queryClient.invalidateQueries({ queryKey: ["parts"] });
      onUploaded(part);
    },
  });

  const choose = (file: File) => {
    upload.reset();
    if (file.name.toLowerCase().endsWith(".stl")) setStl(file);
    else upload.mutate({ file });
  };

  if (stl) {
    return (
      <div className={styles.units}>
        <p className={styles.question}>
          <strong>{stl.name}</strong> is an STL, which doesn't record its units. Was it drawn in millimetres or inches?
        </p>
        <div className={styles.actions}>
          <Button disabled={upload.isPending} onClick={() => upload.mutate({ file: stl, units: "mm" })}>
            Millimetres
          </Button>
          <Button disabled={upload.isPending} onClick={() => upload.mutate({ file: stl, units: "in" })}>
            Inches
          </Button>
          <Button variant="ghost" disabled={upload.isPending} onClick={() => setStl(null)}>
            Choose another file
          </Button>
        </div>
        {upload.isPending && <p className={styles.note}>Reading the part</p>}
        {upload.error && <p className={styles.error}>{upload.error.message}</p>}
      </div>
    );
  }

  return (
    <FileDrop
      label="Drop a STEP or STL file here"
      accept=".step,.stp,.stl"
      busy={upload.isPending ? "Reading the part: measuring it and splitting it into convex pieces" : undefined}
      error={upload.error?.message}
      hint="STEP is best: exact geometry, with its units. From SolidWorks: File > Save As > STEP. Native SolidWorks files can't be read."
      onFile={choose}
    />
  );
}
