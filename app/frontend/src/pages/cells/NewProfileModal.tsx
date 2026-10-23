import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { api, unwrap, type Schemas } from "../../backend/client";
import { Banner } from "../../components/Banner";
import { Button } from "../../components/Button";
import { TextInput } from "../../components/Field";
import { Modal } from "../../components/Modal";
import { Select } from "../../components/Select";

type Saved = Schemas["CellProfileResponse"];

type NewProfileModalProps = {
  open: boolean;
  profiles: Saved[];
  initial?: Saved; // the profile to copy, preselected
  onClose: () => void;
};

/** Names a new cell profile and copies another's settings into it as its version 1, then opens it in the editor. A new
 *  profile always starts from a saved one, so it starts valid; edit the copy to describe the new cell. */
export function NewProfileModal({ open, profiles, initial, onClose }: NewProfileModalProps) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [from, setFrom] = useState("");
  useEffect(() => {
    if (!open) return;
    setName("");
    setFrom(String(initial?.id ?? profiles[0]?.id ?? ""));
  }, [open, initial, profiles]);

  const source = profiles.find((p) => String(p.id) === from);
  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/api/cell-profiles", { body: { name: name.trim(), profile: source!.profile } })),
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: ["cell-profiles"] });
      onClose();
      navigate(`/cells/${saved.id}`);
    },
  });

  return (
    <Modal
      open={open}
      title="New cell"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={create.isPending}>
            Cancel
          </Button>
          <Button onClick={() => create.mutate()} disabled={!name.trim() || !source || create.isPending}>
            Create and edit
          </Button>
        </>
      }
    >
      <TextInput label="Name" value={name} onChange={setName} hint="For example: CSI cell, long-stroke gripper" autoFocus maxLength={100} />
      <Select
        label="Copy the settings of"
        value={from}
        onChange={(event) => setFrom(event.target.value)}
        options={profiles.map((p) => ({ value: String(p.id), label: `${p.name}, version ${p.version}` }))}
        hint="Starts as a copy, placeholder marks included."
      />
      {create.error && <Banner tone="bad">{create.error.message}</Banner>}
    </Modal>
  );
}
