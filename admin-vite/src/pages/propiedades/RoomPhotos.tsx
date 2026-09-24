"use client";

import { useId } from "react";
import { Icon } from "../../components/icons";
import { Input } from "../../components/ui/Input";
import { Textarea } from "../../components/ui/Textarea";

/** Una foto con nombre y descripción: el server la guarda como "<Nombre>.jpg". */
export interface SlotPhoto {
  file: File | null;
  preview: string | null;
  name: string;
  description: string;
}

export function emptySlot(name: string): SlotPhoto {
  return { file: null, preview: null, name, description: "" };
}

interface PhotoSlotCardProps {
  slot: SlotPhoto;
  namePlaceholder: string;
  descriptionPlaceholder: string;
  onPick: (file: File) => void;
  onClear: () => void;
  onRemove?: () => void;
  onName: (value: string) => void;
  onDescription: (value: string) => void;
}

export function PhotoSlotCard({
  slot,
  namePlaceholder,
  descriptionPlaceholder,
  onPick,
  onClear,
  onRemove,
  onName,
  onDescription,
}: PhotoSlotCardProps) {
  const inputId = useId();
  return (
    <div className="slot-card">
      <div className="slot-preview">
        {slot.preview ? (
          <>
            <img src={slot.preview} alt={slot.name || "Foto"} loading="lazy" />
            <button
              type="button"
              className="slot-clear"
              onClick={onClear}
              aria-label="Quitar foto"
              title="Quitar foto"
            >
              <Icon name="x" size={13} />
            </button>
          </>
        ) : (
          <label className="slot-drop" htmlFor={inputId}>
            <Icon name="upload" size={18} />
            <span>Subir foto</span>
          </label>
        )}
        <input
          id={inputId}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f && f.type.startsWith("image/")) onPick(f);
            e.target.value = "";
          }}
          style={{ display: "none" }}
        />
      </div>
      <div className="slot-fields">
        <Input
          label="Nombre de la imagen"
          value={slot.name}
          onChange={(e) => onName(e.target.value)}
          placeholder={namePlaceholder}
          size="sm"
          maxLength={200}
        />
        <Textarea
          label="Descripción"
          value={slot.description}
          onChange={(e) => onDescription(e.target.value)}
          placeholder={descriptionPlaceholder}
          rows={2}
          maxLength={5000}
        />
      </div>
      {onRemove && (
        <button
          type="button"
          className="slot-remove"
          onClick={onRemove}
          aria-label="Eliminar"
          title="Eliminar"
        >
          <Icon name="trash" size={14} />
        </button>
      )}
    </div>
  );
}
