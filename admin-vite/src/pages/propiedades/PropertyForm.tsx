"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Link } from "react-router-dom";
import { backend } from "../../api/client";
import { createProperty, updateProperty, uploadPropertyImage, setPropertyCoverImage, deletePropertyImage, updatePropertyImageMetadata } from "./actions";
import { emptySlot, PhotoSlotCard, type SlotPhoto } from "./RoomPhotos";
import { Button } from "../../components/ui/Button";
import { Input } from "../../components/ui/Input";
import { Select } from "../../components/ui/Select";
import { Textarea } from "../../components/ui/Textarea";
import { CheckboxGroup } from "../../components/ui/CheckboxGroup";
import { ErrorBanner } from "../../components/ErrorBanner";
import { ActionToast, type Feedback } from "../../components/ActionToast";
import { Icon } from "../../components/icons";
import { PROPERTY_TYPES, OPERATIONS } from "../../lib/property-constants";
import {
  FLOOR_OFFER_FULL,
  FLOOR_OFFER_PARTIAL,
  floorChoiceOptions,
  floorOptions,
  normalizeFloorOfferType,
  normalizeOfferedFloors,
  offerFromSelection,
  pruneOfferedFloors,
  uiChoiceFromOffer,
  validateFloorOffer,
} from "../../lib/floors";

interface PropertyFormProps {
  mode: "create" | "edit";
  initialData?: any;
  propertyId?: string;
}

// Grupos de fotografías = características de la propiedad (coinciden con el
// backend: portada, piso, bano, cocina, lavadero, parqueadero, extra).
type RoomKey = "portada" | "piso" | "bano" | "cocina" | "lavadero" | "parqueadero";

const ROOM_META: Record<
  RoomKey,
  { group: string; label: string; defaultName: string; hint: string; icon: "home" | "bed" | "bath" | "star" | "tag" | "car"; fixed: boolean }
> = {
  portada: {
    group: "portada",
    label: "Portada de la casa",
    defaultName: "Portada",
    hint: "Cómo se ve por fuera. Será la imagen principal del aviso.",
    icon: "home",
    fixed: true,
  },
  piso: {
    // Clave de grupo del backend ("piso"): no se cambia para no romper las
    // fotos existentes. Solo cambia la etiqueta visible.
    group: "piso",
    label: "Habitaciones",
    defaultName: "Habitación",
    hint: "Agrega la foto de la habitación. Agrega más si hay varias habitaciones o ángulos.",
    icon: "bed",
    fixed: false,
  },
  bano: {
    group: "bano",
    label: "Baño",
    defaultName: "Baño",
    hint: "Fotos del baño. Agrega más si hay varios baños o ángulos.",
    icon: "bath",
    fixed: false,
  },
  cocina: {
    group: "cocina",
    label: "Cocina",
    defaultName: "Cocina",
    hint: "Fotos de la cocina. Agrega más si tiene varios ángulos.",
    icon: "star",
    fixed: false,
  },
  lavadero: {
    group: "lavadero",
    label: "Lavadero",
    defaultName: "Lavadero",
    hint: "Foto de la zona de lavado.",
    icon: "tag",
    fixed: false,
  },
  parqueadero: {
    group: "parqueadero",
    label: "Parqueadero",
    defaultName: "Parqueadero",
    hint: "Foto del parqueadero.",
    icon: "car",
    fixed: false,
  },
};

const MAX_FILE_MB = 15;
const ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/webp"];

interface CustomExtra {
  id: number;
  name: string;
  photos: SlotPhoto[];
}

interface ExistingImage {
  filename: string;
  name: string;
  description: string;
  isCover: boolean;
  sortOrder: number;
  group: string;
  group_label: string;
  extra_name: string;
}

const GROUP_ORDER = ["portada", "piso", "bano", "cocina", "lavadero", "parqueadero", "extra", "general"];

function defaultRoomPhotos(): Record<RoomKey, SlotPhoto[]> {
  return {
    portada: [emptySlot("Portada")],
    piso: [emptySlot("Habitación")],
    bano: [emptySlot("Baño")],
    cocina: [emptySlot("Cocina")],
    lavadero: [emptySlot("Lavadero")],
    parqueadero: [emptySlot("Parqueadero")],
  };
}

function revokePreview(url: string | null) {
  if (url) {
    try {
      URL.revokeObjectURL(url);
    } catch {
      /* noop */
    }
  }
}

export function PropertyForm({ mode, initialData, propertyId }: PropertyFormProps) {
  const navigate = useNavigate();
  const params = useParams();
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [loading, setLoading] = useState(false);
  const [existingImages, setExistingImages] = useState<ExistingImage[]>([]);
  const [fetchingExisting, setFetchingExisting] = useState(false);
  const [savingImage, setSavingImage] = useState<string | null>(null);
  const [createdId, setCreatedId] = useState<string | null>(null);
  // Fotos por característica: cada una con nombre + descripción propios.
  const [roomPhotos, setRoomPhotos] = useState<Record<RoomKey, SlotPhoto[]>>(defaultRoomPhotos);
  const [extras, setExtras] = useState<CustomExtra[]>([]);
  const extraId = useRef(0);

  const isEditing = mode === "edit";
  const effectivePropertyId = propertyId || params.id;

  const loadExistingImages = useCallback(async () => {
    if (!effectivePropertyId) return;
    setFetchingExisting(true);
    try {
      const propData = await backend<any>(`/properties/${effectivePropertyId}`);
      if (propData.images && Array.isArray(propData.images)) {
        setExistingImages(
          propData.images.map((img: any, idx: number) => ({
            filename: img.filename,
            name: img.name || "",
            description: img.description || "",
            isCover: img.is_cover || idx === 0,
            sortOrder: img.sort_order ?? idx,
            group: img.group || "general",
            group_label: img.group_label || img.group || "general",
            extra_name: img.extra_name || "",
          }))
        );
      } else {
        setExistingImages([]);
      }
    } catch (e) {
      console.error("Error loading existing images:", e);
    } finally {
      setFetchingExisting(false);
    }
  }, [effectivePropertyId]);

  // Load existing images with metadata when editing
  useEffect(() => {
    if (isEditing && effectivePropertyId) {
      loadExistingImages();
    }
  }, [isEditing, effectivePropertyId, loadExistingImages]);

  // Liberar object URLs al desmontar (evita fugas con muchas vistas previas).
  const roomPhotosRef = useRef(roomPhotos);
  roomPhotosRef.current = roomPhotos;
  const extrasRef = useRef(extras);
  extrasRef.current = extras;
  useEffect(() => {
    return () => {
      Object.values(roomPhotosRef.current).flat().forEach((s) => revokePreview(s.preview));
      extrasRef.current.flatMap((x) => x.photos).forEach((s) => revokePreview(s.preview));
    };
  }, []);

  const [formData, setFormData] = useState({
    title: initialData?.title || "",
    property_type: initialData?.property_type || "casa",
    operation: initialData?.operation || "SALE",
    price: initialData?.price || "",
    city: initialData?.city || "",
    neighborhood: initialData?.neighborhood || "",
    nomenclatura: initialData?.nomenclatura || "",
    descriptive_location: initialData?.descriptive_location || "",
    area_m2: initialData?.area_m2 || "",
    bedrooms: initialData?.bedrooms || "",
    bedrooms_description: initialData?.bedrooms_description || "",
    bathrooms: initialData?.bathrooms || "",
    bathrooms_description: initialData?.bathrooms_description || "",
    living_room_description: initialData?.living_room_description || "",
    laundry_area_description: initialData?.laundry_area_description || "",
    parking_spaces: initialData?.parking_spaces || "",
    has_parking: initialData?.has_parking ?? null,
    parking_description: initialData?.parking_description || "",
    services_included: initialData?.services_included ?? null,
    floors: initialData?.floors ?? "",
    floor_offer_type: normalizeFloorOfferType(initialData?.floor_offer_type),
    offered_floors: normalizeOfferedFloors(initialData?.offered_floors),
    has_kitchen: initialData?.has_kitchen ?? true,
    has_living_room: initialData?.has_living_room ?? true,
    has_laundry_area: initialData?.has_laundry_area ?? false,
    features: initialData?.features || [],
    description: initialData?.description || "",
    status: initialData?.status || "AVAILABLE",
  });

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    const { name, value, type } = e.target;
    setFormData((prev) => {
      const next = {
        ...prev,
        [name]: type === "checkbox" ? (e.target as HTMLInputElement).checked : value,
      };
      // En venta siempre se ofrece la propiedad completa: al cambiar a Venta
      // se limpia cualquier selección de pisos (la UI ni la pregunta).
      if (name === "operation" && value === "SALE") {
        next.floor_offer_type = FLOOR_OFFER_FULL;
        next.offered_floors = [];
      }
      return next;
    });
    setFeedback(null);
  }, []);

  // ---- Información de pisos: total físico vs. parte ofertada ----
  // En venta siempre se ofrece la propiedad completa: solo se pide el total.
  const isSale = formData.operation === "SALE";
  const totalFloors: number | null = (() => {
    if (formData.floors === "" || formData.floors === null || formData.floors === undefined) return null;
    const n = typeof formData.floors === "number" ? formData.floors : parseInt(String(formData.floors), 10);
    return Number.isInteger(n) && n >= 1 ? n : null;
  })();
  const dynamicFloorOptions = floorOptions(totalFloors);
  // Opción visible: "full" | "floors" (+ "partial" solo si el registro ya lo trae).
  const uiChoice = uiChoiceFromOffer(formData.floor_offer_type);
  const legacyPartial = normalizeFloorOfferType(initialData?.floor_offer_type) === FLOOR_OFFER_PARTIAL;
  const choiceOptions = floorChoiceOptions(legacyPartial);

  const handleFloorsChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const raw = e.target.value;
    setFormData((prev) => {
      const total = raw === "" ? null : parseInt(raw, 10);
      const pruned = pruneOfferedFloors(
        normalizeOfferedFloors(prev.offered_floors),
        total !== null && Number.isInteger(total) && total >= 1 ? total : null
      );
      return { ...prev, floors: raw, offered_floors: pruned };
    });
    setFeedback(null);
  }, []);

  const handleOfferTypeChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    const choice = e.target.value;
    setFormData((prev) => {
      // Solo hay dos opciones: toda la propiedad o escoger pisos.
      // "partial" solo aparece al editar un registro legado que ya lo trae.
      if (choice === "full") {
        return { ...prev, floor_offer_type: FLOOR_OFFER_FULL, offered_floors: [] };
      }
      if (choice === "partial") {
        return { ...prev, floor_offer_type: FLOOR_OFFER_PARTIAL, offered_floors: [] };
      }
      const offered = normalizeOfferedFloors(prev.offered_floors);
      return {
        ...prev,
        floor_offer_type: offerFromSelection(offered.length),
        offered_floors: offered,
      };
    });
    setFeedback(null);
  }, []);

  const handleMultiFloorToggle = useCallback((value: string, checked: boolean) => {
    const n = parseInt(value, 10);
    setFormData((prev) => {
      const cur = normalizeOfferedFloors(prev.offered_floors);
      const next = checked ? [...cur, n] : cur.filter((x) => x !== n);
      const ordered = [...new Set(next)].sort((a, b) => a - b);
      // 1 piso -> single_floor, 2+ -> multiple_floors (mapeo automático).
      return { ...prev, floor_offer_type: offerFromSelection(ordered.length), offered_floors: ordered };
    });
    setFeedback(null);
  }, []);

  const validatePickedFile = useCallback((file: File): string | null => {
    if (!ACCEPTED_TYPES.includes(file.type)) {
      return "Formato no permitido: usa JPG, PNG o WEBP.";
    }
    if (file.size > MAX_FILE_MB * 1024 * 1024) {
      return `Archivo demasiado grande (máximo ${MAX_FILE_MB} MB).`;
    }
    return null;
  }, []);

  // ---- Fotos por característica ----
  const patchSlot = useCallback((key: RoomKey, index: number, patch: Partial<SlotPhoto>) => {
    setRoomPhotos((prev) => ({
      ...prev,
      [key]: prev[key].map((s, i) => (i === index ? { ...s, ...patch } : s)),
    }));
  }, []);

  const pickSlotFile = useCallback((key: RoomKey, index: number, file: File) => {
    const err = validatePickedFile(file);
    if (err) {
      setFeedback({ tone: "error", message: err });
      return;
    }
    setRoomPhotos((prev) => ({
      ...prev,
      [key]: prev[key].map((s, i) => {
        if (i !== index) return s;
        revokePreview(s.preview);
        return { ...s, file, preview: URL.createObjectURL(file) };
      }),
    }));
  }, [validatePickedFile]);

  const clearSlotFile = useCallback((key: RoomKey, index: number) => {
    setRoomPhotos((prev) => ({
      ...prev,
      [key]: prev[key].map((s, i) => {
        if (i !== index) return s;
        revokePreview(s.preview);
        return { ...s, file: null, preview: null };
      }),
    }));
  }, []);

  const addSlot = useCallback((key: RoomKey) => {
    const meta = ROOM_META[key];
    setRoomPhotos((prev) => ({
      ...prev,
      [key]: [...prev[key], emptySlot(`${meta.defaultName}${prev[key].length + 1}`)],
    }));
  }, []);

  const removeSlot = useCallback((key: RoomKey, index: number) => {
    setRoomPhotos((prev) => ({
      ...prev,
      [key]: prev[key].filter((_, i) => {
        if (i === index) revokePreview(prev[key][i].preview);
        return i !== index;
      }),
    }));
  }, []);

  // ---- Extras personalizados (cada extra: nombre + N fotos con descripción) ----
  const addExtra = useCallback(() => {
    extraId.current += 1;
    setExtras((prev) => [
      ...prev,
      { id: extraId.current, name: "", photos: [emptySlot("Foto")] },
    ]);
  }, []);

  const patchExtraName = useCallback((id: number, name: string) => {
    setExtras((prev) => prev.map((x) => (x.id === id ? { ...x, name } : x)));
  }, []);

  const addExtraPhoto = useCallback((id: number) => {
    setExtras((prev) =>
      prev.map((x) => {
        if (x.id !== id) return x;
        const base = x.name.trim() || "Foto";
        return { ...x, photos: [...x.photos, emptySlot(`${base}${x.photos.length + 1}`)] };
      })
    );
  }, []);

  const patchExtraPhoto = useCallback((id: number, index: number, patch: Partial<SlotPhoto>) => {
    setExtras((prev) =>
      prev.map((x) =>
        x.id === id
          ? { ...x, photos: x.photos.map((s, i) => (i === index ? { ...s, ...patch } : s)) }
          : x
      )
    );
  }, []);

  const pickExtraPhoto = useCallback((id: number, index: number, file: File) => {
    const err = validatePickedFile(file);
    if (err) {
      setFeedback({ tone: "error", message: err });
      return;
    }
    setExtras((prev) =>
      prev.map((x) =>
        x.id === id
          ? {
              ...x,
              photos: x.photos.map((s, i) => {
                if (i !== index) return s;
                revokePreview(s.preview);
                return { ...s, file, preview: URL.createObjectURL(file) };
              }),
            }
          : x
      )
    );
  }, [validatePickedFile]);

  const clearExtraPhoto = useCallback((id: number, index: number) => {
    setExtras((prev) =>
      prev.map((x) =>
        x.id === id
          ? {
              ...x,
              photos: x.photos.map((s, i) => {
                if (i !== index) return s;
                revokePreview(s.preview);
                return { ...s, file: null, preview: null };
              }),
            }
          : x
      )
    );
  }, []);

  const removeExtraPhoto = useCallback((id: number, index: number) => {
    setExtras((prev) =>
      prev.map((x) =>
        x.id === id
          ? {
              ...x,
              photos: x.photos.filter((s, i) => {
                if (i === index) revokePreview(s.preview);
                return i !== index;
              }),
            }
          : x
      )
    );
  }, []);

  const removeExtra = useCallback((id: number) => {
    setExtras((prev) => {
      const target = prev.find((x) => x.id === id);
      target?.photos.forEach((s) => revokePreview(s.preview));
      return prev.filter((x) => x.id !== id);
    });
  }, []);

  // ---- Imágenes existentes (modo edición, agrupadas por característica) ----
  const patchExisting = useCallback((filename: string, patch: Partial<ExistingImage>) => {
    setExistingImages((prev) =>
      prev.map((img) => (img.filename === filename ? { ...img, ...patch } : img))
    );
  }, []);

  const saveExistingMeta = useCallback(async (filename: string) => {
    if (!effectivePropertyId) return;
    const img = existingImages.find((i) => i.filename === filename);
    if (!img) return;
    if (img.name.length > 200) {
      setFeedback({ tone: "error", message: "El nombre de la imagen no puede exceder 200 caracteres." });
      return;
    }
    if (img.description.length > 5000) {
      setFeedback({ tone: "error", message: "La descripción de la imagen no puede exceder 5000 caracteres." });
      return;
    }
    setSavingImage(filename);
    const res = await updatePropertyImageMetadata(
      effectivePropertyId, filename, img.name, img.description
    );
    setSavingImage(null);
    setFeedback(res.ok
      ? { tone: "ok", message: "Imagen actualizada." }
      : { tone: "error", message: res.error });
  }, [effectivePropertyId, existingImages]);

  const handleDeleteExistingImage = useCallback(async (filename: string) => {
    if (!effectivePropertyId) return;
    if (!confirm(`¿Eliminar la imagen ${filename}?`)) return;
    const res = await deletePropertyImage(effectivePropertyId, filename);
    if (res.ok) {
      setExistingImages((prev) => prev.filter((f) => f.filename !== filename));
      setFeedback({ tone: "ok", message: "Imagen eliminada." });
    } else {
      setFeedback({ tone: "error", message: res.error });
    }
  }, [effectivePropertyId]);

  const handleSetCoverExisting = useCallback(async (filename: string) => {
    if (!effectivePropertyId) return;
    const res = await setPropertyCoverImage(effectivePropertyId, filename);
    if (res.ok) {
      await loadExistingImages();
      setFeedback({ tone: "ok", message: "Portada actualizada." });
    } else {
      setFeedback({ tone: "error", message: res.error });
    }
  }, [effectivePropertyId, loadExistingImages]);

  const validatePhotoQueue = useCallback((): string | null => {
    const check = (name: string, description: string, label: string): string | null => {
      if (name.length > 200) return `El nombre de "${label}" no puede exceder 200 caracteres.`;
      if (description.length > 5000) return `La descripción de "${label}" no puede exceder 5000 caracteres.`;
      return null;
    };
    for (const key of Object.keys(roomPhotos) as RoomKey[]) {
      if (key === "parqueadero" && !formData.has_parking) continue;
      for (const s of roomPhotos[key]) {
        if (!s.file) continue;
        const err = check(s.name.trim(), s.description.trim(), s.name.trim() || ROOM_META[key].defaultName);
        if (err) return err;
      }
    }
    for (const x of extras) {
      const hasFile = x.photos.some((p) => p.file);
      const hasText = x.name.trim() || x.photos.some((p) => p.description.trim());
      if (x.photos.length === 0) return "Cada extra debe tener al menos una foto o elimínalo.";
      if (hasFile && !x.name.trim()) {
        return "Ponle nombre a cada extra personalizado (ej. Piscina, Chimenea).";
      }
      if (!hasFile && hasText) {
        return `Sube la foto de "${x.name.trim() || "el extra"}" o elimínalo.`;
      }
      for (const p of x.photos) {
        if (!p.file) continue;
        const err = check(p.name.trim(), p.description.trim(), p.name.trim() || x.name.trim());
        if (err) return err;
      }
    }
    return null;
  }, [roomPhotos, extras, formData.has_parking]);

  const handleSubmit = useCallback(async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (loading) return; // evita doble envío por doble clic
    setFeedback(null);
    setCreatedId(null);

    const choice = uiChoiceFromOffer(formData.floor_offer_type);
    if (!isSale && choice === "floors" && normalizeOfferedFloors(formData.offered_floors).length === 0) {
      setFeedback({ tone: "error", message: "Escoge al menos un piso a arrendar" });
      return;
    }
    const floorError = validateFloorOffer(totalFloors, formData.floor_offer_type, formData.offered_floors);
    if (floorError) {
      setFeedback({ tone: "error", message: floorError });
      return;
    }

    const queue: { file: File; name: string; description: string; group: string; extraName: string; isCover: boolean }[] = [];
    const pushSlots = (key: RoomKey) => {
      for (const s of roomPhotos[key]) {
        if (!s.file) continue;
        queue.push({
          file: s.file,
          name: s.name.trim() || `${ROOM_META[key].defaultName}${queue.length + 1}`,
          description: s.description.trim(),
          group: ROOM_META[key].group,
          extraName: "",
          isCover: false,
        });
      }
    };

    // Extras personalizados pasan a características para que el buscador los encuentre
    const extraNames = extras.map((x) => x.name.trim()).filter((n) => n.length > 0);
    const mergedFeatures = [...formData.features, ...extraNames.filter((n) => !formData.features.includes(n))];

    const submitData = new FormData();
    Object.entries({ ...formData, features: mergedFeatures }).forEach(([key, value]) => {
      if (value !== "" && value !== undefined && value !== null) {
        if (key === "features" || key === "offered_floors") {
          submitData.append(key, JSON.stringify(value));
        } else if (typeof value === "boolean") {
          submitData.append(key, value ? "true" : "false");
        } else {
          submitData.append(key, String(value));
        }
      }
    });
    // En venta siempre se ofrece la propiedad completa (la UI ni lo pregunta).
    if (isSale) {
      submitData.set("floor_offer_type", FLOOR_OFFER_FULL);
      submitData.set("offered_floors", "[]");
    }

    setLoading(true);
    try {
      if (isEditing && effectivePropertyId) {
        const result = await updateProperty(effectivePropertyId, submitData);
        if (!result.ok) {
          setFeedback({ tone: "error", message: result.error });
          return;
        }
        // Subir fotos nuevas agrupadas por característica
        const photoError = validatePhotoQueue();
        if (photoError) {
          setFeedback({ tone: "error", message: photoError });
          return;
        }
        pushSlots("portada");
        (["piso", "bano", "cocina", "lavadero"] as RoomKey[]).forEach(pushSlots);
        if (formData.has_parking) pushSlots("parqueadero");
        for (const x of extras) {
          for (const p of x.photos) {
            if (!p.file) continue;
            queue.push({
              file: p.file, name: p.name.trim() || x.name.trim(),
              description: p.description.trim(), group: "extra",
              extraName: x.name.trim(), isCover: false,
            });
          }
        }
        const failed: string[] = [];
        for (let i = 0; i < queue.length; i++) {
          const item = queue[i];
          setFeedback({ tone: "ok", message: `Subiendo fotos… ${i + 1} de ${queue.length}` });
          const up = await uploadPropertyImage(
            effectivePropertyId, item.file, item.name, item.description, item.group, item.extraName
          );
          if (!up.ok) failed.push(item.name);
        }
        await loadExistingImages();
        if (failed.length > 0) {
          setFeedback({
            tone: "error",
            message: `Propiedad actualizada, pero no se pudieron subir: ${failed.join(", ")}.`,
          });
        } else {
          setFeedback({ tone: "ok", message: "Propiedad actualizada correctamente" });
          setTimeout(() => navigate("/propiedades", { replace: true }), 1200);
        }
        return;
      }

      // ---- Modo crear: validar fotos por característica ----
      const cover = roomPhotos.portada[0];
      if (!cover?.file) {
        setFeedback({ tone: "error", message: "Sube la foto de portada de la casa (cómo se ve por fuera)." });
        return;
      }
      const photoError = validatePhotoQueue();
      if (photoError) {
        setFeedback({ tone: "error", message: photoError });
        return;
      }

      const result = await createProperty(submitData);
      if (!result.ok || !result.property) {
        setFeedback({ tone: "error", message: result.ok ? "No se pudo crear la propiedad" : result.error });
        return;
      }
      const newId = String(result.property.id);
      setCreatedId(newId);

      // ---- Subir fotos con nombre + descripción + grupo (la portada primero) ----
      if (cover.file) {
        queue.push({
          file: cover.file,
          name: cover.name.trim() || "Portada",
          description: cover.description.trim(),
          group: "portada",
          extraName: "",
          isCover: true,
        });
      }
      (["piso", "bano", "cocina", "lavadero"] as RoomKey[]).forEach(pushSlots);
      if (formData.has_parking) pushSlots("parqueadero");
      for (const x of extras) {
        for (const p of x.photos) {
          if (!p.file) continue;
          queue.push({
            file: p.file, name: p.name.trim() || x.name.trim(),
            description: p.description.trim(), group: "extra",
            extraName: x.name.trim(), isCover: false,
          });
        }
      }

      const failed: string[] = [];
      let coverFilename: string | null = null;
      for (let i = 0; i < queue.length; i++) {
        const item = queue[i];
        setFeedback({ tone: "ok", message: `Subiendo fotos… ${i + 1} de ${queue.length}` });
        const up = await uploadPropertyImage(
          newId, item.file, item.name, item.description, item.group, item.extraName
        );
        const saved = up.ok ? (up.property as any)?.saved ?? (up.property as any)?.image?.filename : null;
        if (!up.ok || !saved) {
          failed.push(item.name);
        } else if (item.isCover) {
          coverFilename = String(saved);
        }
      }
      if (coverFilename) {
        await setPropertyCoverImage(newId, coverFilename).catch(() => undefined);
      }

      if (failed.length > 0) {
        setFeedback({
          tone: "error",
          message: `Propiedad creada, pero no se pudieron subir: ${failed.join(", ")}.`,
        });
      } else {
        setFeedback({ tone: "ok", message: "Propiedad creada correctamente" });
        setTimeout(() => navigate(`/propiedades/${newId}`), 1200);
      }
    } catch (e) {
      setFeedback({ tone: "error", message: e instanceof Error ? e.message : "Error desconocido" });
    } finally {
      setLoading(false);
    }
  }, [formData, isEditing, effectivePropertyId, navigate, roomPhotos, extras, loading, validatePhotoQueue, loadExistingImages]);

  const showRentFields = formData.operation === "RENT";

  const existingByGroup = (group: string) =>
    existingImages
      .filter((img) => img.group === group)
      .sort((a, b) => a.sortOrder - b.sortOrder);

  const renderExistingCard = (img: ExistingImage) => (
    <div key={img.filename} className="slot-card slot-card-existing">
      <div className="slot-preview">
        <img
          src={`/api/properties/${effectivePropertyId}/images/${img.filename}`}
          alt={img.name || img.filename}
          loading="lazy"
        />
        {img.isCover && <span className="cover-badge">Portada</span>}
      </div>
      <div className="slot-fields">
        {img.group === "extra" && img.extra_name && (
          <p className="slot-extra-name">Extra: {img.extra_name}</p>
        )}
        <Input
          label="Nombre de la imagen"
          value={img.name}
          onChange={(e) => patchExisting(img.filename, { name: e.target.value })}
          placeholder="Ej: Baño principal"
          size="sm"
          maxLength={200}
        />
        <Textarea
          label="Descripción"
          value={img.description}
          onChange={(e) => patchExisting(img.filename, { description: e.target.value })}
          placeholder="Ej: Baño principal con ducha…"
          rows={2}
          maxLength={5000}
        />
        <div className="slot-existing-actions">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={savingImage === img.filename}
            onClick={() => saveExistingMeta(img.filename)}
          >
            {savingImage === img.filename ? "Guardando…" : "Guardar"}
          </Button>
          {!img.isCover && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => handleSetCoverExisting(img.filename)}
              aria-label="Establecer como portada"
            >
              <Icon name="star" size={14} />
            </Button>
          )}
          <Button
            type="button"
            variant="danger"
            size="sm"
            onClick={() => handleDeleteExistingImage(img.filename)}
            aria-label="Eliminar imagen"
          >
            <Icon name="trash" size={14} />
          </Button>
        </div>
      </div>
    </div>
  );

  const renderRoomSection = (
    num: number,
    key: RoomKey,
    titleSuffix = ""
  ) => {
    const meta = ROOM_META[key];
    return (
      <section className="card form-section" aria-labelledby={`room-${key}-heading`}>
        <header className="card-head">
          <h2 id={`room-${key}-heading`} className="section-title">
            <Icon name={meta.icon} size={18} /> {num}. {meta.label}{titleSuffix}
          </h2>
          <p className="section-hint">{meta.hint} El servidor la guarda como «Nombre.jpg».</p>
        </header>
        <div className="card-body room-list">
          <div className="room-block">
            <div className="slot-grid">
              {isEditing &&
                existingByGroup(meta.group).map((img) => renderExistingCard(img))}
              {roomPhotos[key].map((slot, i) => (
                <PhotoSlotCard
                  key={`${key}-new-${i}`}
                  slot={slot}
                  namePlaceholder={`Ej: ${slot.name || meta.defaultName}`}
                  descriptionPlaceholder="Describe lo que se ve en la foto…"
                  onPick={(f) => pickSlotFile(key, i, f)}
                  onClear={() => clearSlotFile(key, i)}
                  onRemove={
                    !meta.fixed && roomPhotos[key].length > 1
                      ? () => removeSlot(key, i)
                      : undefined
                  }
                  onName={(v) => patchSlot(key, i, { name: v })}
                  onDescription={(v) => patchSlot(key, i, { description: v })}
                />
              ))}
              {!meta.fixed && (
                <div className="slot-add">
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    onClick={() => addSlot(key)}
                    icon={<Icon name="plus" size={14} />}
                    iconPosition="left"
                  >
                    Agregar otra foto
                  </Button>
                </div>
              )}
            </div>
          </div>
        </div>
      </section>
    );
  };

  return (
    <div className="property-form-container">
      <ActionToast feedback={feedback} onClose={() => setFeedback(null)} />
      {feedback?.tone === "error" && <ErrorBanner title="Error" message={feedback.message} />}

      <form onSubmit={handleSubmit} className="property-form" noValidate>
        {/* 1. Informe principal (sin Moneda: siempre COP) */}
        <section className="card form-section" aria-labelledby="basic-info-heading">
          <header className="card-head">
            <h2 id="basic-info-heading" className="section-title">
              <Icon name="info" size={18} /> 1. Informe principal
            </h2>
          </header>
          <div className="card-body form-grid">
            <Input
              label="Nombre de la propiedad *"
              name="title"
              value={formData.title}
              onChange={handleChange}
              placeholder="Ej: Casa familiar en barrio Laureles"
              required
              maxLength={200}
            />
            <Select
              label="Tipo de propiedad *"
              name="property_type"
              value={formData.property_type}
              onChange={handleChange}
              options={PROPERTY_TYPES.map((t) => ({ value: t, label: t.charAt(0).toUpperCase() + t.slice(1) }))}
              required
            />
            <Select
              label="Operación *"
              name="operation"
              value={formData.operation}
              onChange={handleChange}
              options={OPERATIONS.map((o) => ({ value: o, label: o === "SALE" ? "Venta" : "Arriendo" }))}
              required
            />
            <Input
              label={formData.operation === "RENT" ? "Precio del arriendo (mensual) *" : "Precio de venta *"}
              name="price"
              type="number"
              step="1"
              min="1"
              value={formData.price}
              onChange={handleChange}
              placeholder="1800000"
              required
            />
            {showRentFields && (
              <div className="form-field">
                <span className="form-label" id="services-label">¿Servicios públicos?</span>
                <div className="segmented" role="group" aria-labelledby="services-label">
                  <button
                    type="button"
                    className={formData.services_included === "no_incluye" ? "active" : ""}
                    aria-pressed={formData.services_included === "no_incluye"}
                    onClick={() => setFormData((prev) => ({ ...prev, services_included: "no_incluye" }))}
                  >
                    No
                  </button>
                  <button
                    type="button"
                    className={formData.services_included === "incluye" ? "active" : ""}
                    aria-pressed={formData.services_included === "incluye"}
                    onClick={() => setFormData((prev) => ({ ...prev, services_included: "incluye" }))}
                  >
                    Sí
                  </button>
                </div>
              </div>
            )}
          </div>
        </section>

        {/* 2. Ubicación (implementación existente, sin cambios) */}
        <section className="card form-section" aria-labelledby="location-heading">
          <header className="card-head">
            <h2 id="location-heading" className="section-title">
              <Icon name="map-pin" size={18} /> 2. Ubicación
            </h2>
          </header>
          <div className="card-body form-grid">
            <Input
              label="Ciudad *"
              name="city"
              value={formData.city}
              onChange={handleChange}
              placeholder="Ej: Carepa"
              required
              maxLength={80}
            />
            <Input
              label="Barrio / Sector *"
              name="neighborhood"
              value={formData.neighborhood}
              onChange={handleChange}
              placeholder="Ej: El Centro"
              required
              maxLength={120}
            />
            <Input
              label="Nomenclatura formal *"
              name="nomenclatura"
              value={formData.nomenclatura}
              onChange={handleChange}
              placeholder="Ej: Calle 100 # 50-20"
              required
              maxLength={240}
            />
            <Textarea
              label="Descripción de ubicación / Cómo llegar"
              name="descriptive_location"
              value={formData.descriptive_location}
              onChange={handleChange}
              placeholder="Ej: Desde la sede principal tomar la vía hacia el parque principal y continuar dos cuadras."
              rows={3}
              maxLength={500}
            />
          </div>
        </section>

        {/* 3. Características + Información de pisos */}
        <section className="card form-section" aria-labelledby="characteristics-heading">
          <header className="card-head">
            <h2 id="characteristics-heading" className="section-title">
              <Icon name="home" size={18} /> 3. Características
            </h2>
          </header>
          <div className="card-body form-grid">
            <Input
              label="Metros cuadrados (m²)"
              name="area_m2"
              type="number"
              step="0.01"
              min="0"
              value={formData.area_m2}
              onChange={handleChange}
              placeholder="Ej: 120"
            />
            <Input
              label="Habitaciones (cantidad)"
              name="bedrooms"
              type="number"
              step="1"
              min="0"
              max="99"
              value={formData.bedrooms}
              onChange={handleChange}
              placeholder="Ej: 3"
            />
            <Input
              label="Baños (cantidad)"
              name="bathrooms"
              type="number"
              step="1"
              min="0"
              max="99"
              value={formData.bathrooms}
              onChange={handleChange}
              placeholder="Ej: 2"
            />
            <Input
              label="Número de pisos"
              name="floors"
              type="number"
              step="1"
              min="1"
              max="99"
              value={formData.floors}
              onChange={handleFloorsChange}
              placeholder="Ej: 2"
              hint="¿Cuántos pisos tiene la propiedad completa?"
            />
            {!isSale && (
              <Select
                label="¿Qué parte de la propiedad se ofrece?"
                name="floor_offer_choice"
                value={uiChoice === "partial" ? "partial" : uiChoice}
                onChange={handleOfferTypeChange}
                options={choiceOptions}
                required
                hint="Toda la propiedad o escoge los pisos que se van a arrendar."
              />
            )}
            {!isSale && uiChoice === "full" && totalFloors !== null && (
              <p className="form-hint" style={{ gridColumn: "1 / -1", margin: 0 }}>
                Se arrienda toda la propiedad ({totalFloors} {totalFloors === 1 ? "piso" : "pisos"}).
              </p>
            )}
            {!isSale && uiChoice === "floors" && (
              <div className="form-field" style={{ gridColumn: "1 / -1" }}>
                <span className="form-label" id="offered-floors-label">Pisos que se arriendan</span>
                {totalFloors === null ? (
                  <p className="form-hint" style={{ margin: 0 }}>
                    Primero indica el número total de pisos.
                  </p>
                ) : (
                  <>
                    <CheckboxGroup
                      name="Pisos que se arriendan"
                      options={dynamicFloorOptions}
                      value={formData.offered_floors.map(String)}
                      onChange={handleMultiFloorToggle}
                      columns={totalFloors > 4 ? 4 : 2}
                    />
                    <p className="form-hint" style={{ margin: "4px 0 0" }}>
                      Puedes escoger uno o varios (ej. una casa de 3 pisos puede arrendar el 2 y el 3).
                    </p>
                  </>
                )}
              </div>
            )}
            {!isSale && uiChoice === "partial" && (
              <p className="form-hint" style={{ gridColumn: "1 / -1", margin: 0 }}>
                Describe la parte ofertada (apartamento interior, anexo, habitación
                independiente…) en la Descripción general de la propiedad.
              </p>
            )}
            <div className="form-field">
              <span className="form-label" id="kitchen-label">¿Tiene cocina?</span>
              <div className="segmented" role="group" aria-labelledby="kitchen-label">
                <button
                  type="button"
                  className={formData.has_kitchen === false ? "active" : ""}
                  aria-pressed={formData.has_kitchen === false}
                  onClick={() => setFormData((prev) => ({ ...prev, has_kitchen: false }))}
                >
                  No
                </button>
                <button
                  type="button"
                  className={formData.has_kitchen !== false ? "active" : ""}
                  aria-pressed={formData.has_kitchen !== false}
                  onClick={() => setFormData((prev) => ({ ...prev, has_kitchen: true }))}
                >
                  Sí
                </button>
              </div>
            </div>
            <div className="form-field">
              <span className="form-label" id="living-room-label">¿Tiene sala?</span>
              <div className="segmented" role="group" aria-labelledby="living-room-label">
                <button
                  type="button"
                  className={formData.has_living_room === false ? "active" : ""}
                  aria-pressed={formData.has_living_room === false}
                  onClick={() => setFormData((prev) => ({ ...prev, has_living_room: false }))}
                >
                  No
                </button>
                <button
                  type="button"
                  className={formData.has_living_room !== false ? "active" : ""}
                  aria-pressed={formData.has_living_room !== false}
                  onClick={() => setFormData((prev) => ({ ...prev, has_living_room: true }))}
                >
                  Sí
                </button>
              </div>
            </div>
            <div className="form-field">
              <span className="form-label" id="laundry-label">¿Tiene zona de lavado?</span>
              <div className="segmented" role="group" aria-labelledby="laundry-label">
                <button
                  type="button"
                  className={formData.has_laundry_area === true ? "" : "active"}
                  aria-pressed={formData.has_laundry_area !== true}
                  onClick={() => setFormData((prev) => ({ ...prev, has_laundry_area: false }))}
                >
                  No
                </button>
                <button
                  type="button"
                  className={formData.has_laundry_area === true ? "active" : ""}
                  aria-pressed={formData.has_laundry_area === true}
                  onClick={() => setFormData((prev) => ({ ...prev, has_laundry_area: true }))}
                >
                  Sí
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* 4–8. Fotografías por característica */}
        {renderRoomSection(4, "portada", " *")}
        {renderRoomSection(5, "piso")}
        {renderRoomSection(6, "bano")}
        {renderRoomSection(7, "cocina")}
        {renderRoomSection(8, "lavadero")}

        {/* 9. Parqueadero */}
        <section className="card form-section" aria-labelledby="parking-heading">
          <header className="card-head">
            <h2 id="parking-heading" className="section-title">
              <Icon name="car" size={18} /> 9. Parqueadero
            </h2>
          </header>
          <div className="card-body form-grid">
            <div className="form-field">
              <span className="form-label" id="parking-label">¿Tiene parqueadero?</span>
              <div className="segmented" role="group" aria-labelledby="parking-label">
                <button
                  type="button"
                  className={formData.has_parking === false ? "active" : ""}
                  aria-pressed={formData.has_parking === false}
                  onClick={() => setFormData((prev) => ({ ...prev, has_parking: false }))}
                >
                  No
                </button>
                <button
                  type="button"
                  className={formData.has_parking === true ? "active" : ""}
                  aria-pressed={formData.has_parking === true}
                  onClick={() => setFormData((prev) => ({ ...prev, has_parking: true }))}
                >
                  Sí
                </button>
              </div>
            </div>
            {formData.has_parking === true && (
              <>
                <Input
                  label="Parqueaderos (cantidad)"
                  name="parking_spaces"
                  type="number"
                  min="0"
                  max="99"
                  value={formData.parking_spaces}
                  onChange={handleChange}
                  placeholder="Ej: 1"
                />
                <Textarea
                  label="Descripción del parqueadero"
                  name="parking_description"
                  value={formData.parking_description}
                  onChange={handleChange}
                  placeholder="Ej: Parqueadero cubierto para un vehículo."
                  rows={2}
                  maxLength={5000}
                />
              </>
            )}
          </div>
          {(formData.has_parking || (isEditing && existingByGroup("parqueadero").length > 0)) && (
            <div className="card-body room-list">
              <div className="room-block">
                <div className="room-head">
                  <span className="room-icon" aria-hidden="true">
                    <Icon name="car" size={16} />
                  </span>
                  <div className="room-titles">
                    <h3 className="room-title">Fotos del parqueadero</h3>
                    <p className="room-hint">Documenta el parqueadero si lo deseas.</p>
                  </div>
                </div>
                <div className="slot-grid">
                  {isEditing &&
                    existingByGroup("parqueadero").map((img) => renderExistingCard(img))}
                  {roomPhotos.parqueadero.map((slot, i) => (
                    <PhotoSlotCard
                      key={`parqueadero-new-${i}`}
                      slot={slot}
                      namePlaceholder={`Ej: ${slot.name || "Parqueadero"}`}
                      descriptionPlaceholder="Ej: Parqueadero cubierto para un vehículo…"
                      onPick={(f) => pickSlotFile("parqueadero", i, f)}
                      onClear={() => clearSlotFile("parqueadero", i)}
                      onRemove={
                        roomPhotos.parqueadero.length > 1
                          ? () => removeSlot("parqueadero", i)
                          : undefined
                      }
                      onName={(v) => patchSlot("parqueadero", i, { name: v })}
                      onDescription={(v) => patchSlot("parqueadero", i, { description: v })}
                    />
                  ))}
                  <div className="slot-add">
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      onClick={() => addSlot("parqueadero")}
                      icon={<Icon name="plus" size={14} />}
                      iconPosition="left"
                    >
                      Agregar otra foto
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          )}
        </section>

        {/* 10. Extras personalizadas (características adicionales) */}
        <section className="card form-section" aria-labelledby="extras-heading">
          <header className="card-head">
            <h2 id="extras-heading" className="section-title">
              <Icon name="plus" size={18} /> 10. Extras personalizadas
            </h2>
            <p className="section-hint">Piscina, chimenea, BBQ…: escribe el nombre, sube las fotos y describe cada una.</p>
          </header>
          <div className="card-body room-list">
            {isEditing && existingImages.some((img) => img.group === "extra" || img.group === "general") && (
              <div className="room-block">
                <div className="room-head">
                  <div className="room-titles">
                    <h3 className="room-title">Extras y fotos anteriores</h3>
                    <p className="room-hint">Fotos de extras o del formato anterior, agrupadas por característica.</p>
                  </div>
                </div>
                <div className="slot-grid">
                  {GROUP_ORDER.filter((g) => g === "extra" || g === "general").map((g) =>
                    existingByGroup(g).map((img) => renderExistingCard(img))
                  )}
                </div>
              </div>
            )}
            {fetchingExisting && isEditing && (
              <p className="extras-empty">Cargando imágenes existentes…</p>
            )}
            {extras.length === 0 && (
              <p className="extras-empty">Sin extras. Agrega características propias de esta casa (piscina, chimenea…).</p>
            )}
            {extras.map((x) => (
              <div key={x.id} className="room-block extra-block">
                <div className="room-head">
                  <div className="room-titles extra-name-wrap">
                    <Input
                      label="Nombre del extra"
                      value={x.name}
                      onChange={(e) => patchExtraName(x.id, e.target.value)}
                      placeholder="Ej: Piscina, Chimenea…"
                      size="sm"
                      maxLength={200}
                    />
                  </div>
                  <div className="room-action">
                    <Button
                      type="button"
                      variant="danger"
                      size="sm"
                      onClick={() => removeExtra(x.id)}
                      icon={<Icon name="trash" size={14} />}
                      iconPosition="left"
                    >
                      Eliminar
                    </Button>
                  </div>
                </div>
                <div className="slot-grid">
                  {x.photos.map((slot, i) => (
                    <PhotoSlotCard
                      key={`${x.id}-${i}`}
                      slot={slot}
                      namePlaceholder={`Ej: ${x.name.trim() || "Piscina"}${x.photos.length > 1 ? ` ${i + 1}` : ""}`}
                      descriptionPlaceholder="Describe lo que se ve en la foto…"
                      onPick={(f) => pickExtraPhoto(x.id, i, f)}
                      onClear={() => clearExtraPhoto(x.id, i)}
                      onRemove={
                        x.photos.length > 1
                          ? () => removeExtraPhoto(x.id, i)
                          : undefined
                      }
                      onName={(v) => patchExtraPhoto(x.id, i, { name: v })}
                      onDescription={(v) => patchExtraPhoto(x.id, i, { description: v })}
                    />
                  ))}
                  <div className="slot-add">
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      onClick={() => addExtraPhoto(x.id)}
                      icon={<Icon name="plus" size={14} />}
                      iconPosition="left"
                    >
                      Agregar otra foto
                    </Button>
                  </div>
                </div>
              </div>
            ))}
            <div className="extras-add">
              <Button type="button" variant="secondary" onClick={addExtra} icon={<Icon name="plus" size={14} />} iconPosition="left">
                Agregar personalizado
              </Button>
            </div>
          </div>
        </section>

        {/* 11. Descripción general (separada de las descripciones de cada foto) */}
        <section className="card form-section" aria-labelledby="description-heading">
          <header className="card-head">
            <h2 id="description-heading" className="section-title">
              <Icon name="file-text" size={18} /> 11. Descripción general
            </h2>
          </header>
          <div className="card-body">
            <Textarea
              label="Descripción general de la propiedad"
              name="description"
              value={formData.description}
              onChange={handleChange}
              placeholder="Describe la propiedad, sus acabados, entorno, cercanías..."
              rows={5}
              maxLength={10000}
            />
          </div>
        </section>

        {/* Estado Comercial (solo edición) */}
        {isEditing && (
          <section className="card form-section" aria-labelledby="status-heading">
            <header className="card-head">
              <h2 id="status-heading" className="section-title">
                <Icon name="toggle" size={18} /> Estado Comercial
              </h2>
            </header>
            <div className="card-body">
              <Select
                label="Estado"
                name="status"
                value={formData.status}
                onChange={handleChange}
                options={[
                  { value: "AVAILABLE", label: "Disponible" },
                  { value: "RESERVED", label: "Reservada" },
                  { value: "SOLD", label: "Vendida" },
                  { value: "INACTIVE", label: "Inactiva" },
                ]}
              />
            </div>
          </section>
        )}

        {/* 12. Acciones */}
        <footer className="form-footer form-footer-bar">
          <Link to="/propiedades" className="btn btn-ghost btn-lg">
            <Icon name="x" size={16} />
            Cancelar
          </Link>
          <Button type="submit" loading={loading} disabled={loading} variant="primary" size="lg" iconPosition="left" icon={<Icon name={isEditing ? "save" : "plus"} size={16} />}>
            {loading ? "Guardando…" : isEditing ? "Guardar cambios" : "Crear propiedad"}
          </Button>
        </footer>
      </form>
      {createdId && (
        <p className="form-created-link">
          <Link to={`/propiedades/${createdId}`} className="btn btn-secondary">
            <Icon name="eye" size={14} />
            Ver propiedad creada
          </Link>
        </p>
      )}
    </div>
  );
}
