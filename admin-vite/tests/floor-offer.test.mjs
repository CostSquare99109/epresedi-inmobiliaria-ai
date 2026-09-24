// Validación del modelo de pisos (refleja admin-vite/src/lib/floors.ts).
// Ejecutar: npm run test:floors  (o node tests/floor-offer.test.mjs)
import {
  FLOOR_OFFER_FULL,
  FLOOR_OFFER_MULTIPLE,
  FLOOR_OFFER_PARTIAL,
  FLOOR_OFFER_SINGLE,
  floorChoiceOptions,
  floorOptions,
  formatFloorsDisplay,
  normalizeFloorOfferType,
  normalizeOfferedFloors,
  offerFromSelection,
  pruneOfferedFloors,
  uiChoiceFromOffer,
  validateFloorOffer,
} from "../src/lib/floors.ts";

let failures = 0;
function check(name, actual, expected) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) {
    failures += 1;
    console.error(`FAIL ${name}: esperado ${e}, obtenido ${a}`);
  } else {
    console.log(`ok ${name}`);
  }
}

// Aceptación: venta + arriendo completo + pisos individuales + varios
check("venta 2 pisos completa", validateFloorOffer(2, "full_property", []), null);
check("arriendo 2 pisos completa", validateFloorOffer(2, "full_property", []), null);
check("arriendo piso 1", validateFloorOffer(2, "single_floor", [1]), null);
check("arriendo piso 2", validateFloorOffer(2, "single_floor", [2]), null);
check("arriendo varios 1 y 2", validateFloorOffer(3, "multiple_floors", [1, 2]), null);
check("parte de la propiedad", validateFloorOffer(2, "partial", []), null);
check("legado sin datos", validateFloorOffer(null, "full_property", []), null);
check("legado tipo desconocido", normalizeFloorOfferType("inexistente"), FLOOR_OFFER_FULL);
check("legado offered null", normalizeOfferedFloors(null), []);

// Inválidos: deben devolver mensaje (no null)
for (const [name, args] of [
  ["2 pisos + piso 3", [2, "single_floor", [3]]],
  ["piso completo sin selección", [2, "single_floor", []]],
  ["piso completo con dos", [2, "single_floor", [1, 2]]],
  ["varios sin selección", [3, "multiple_floors", []]],
  ["completa con pisos", [2, "full_property", [1]]],
  ["cero pisos", [0, "full_property", []]],
  ["pisos sin total", [null, "single_floor", [1]]],
]) {
  const err = validateFloorOffer(...args);
  check(`${name} se rechaza`, typeof err === "string" && err.length > 0, true);
}

// Cambio dinámico 4 -> 2 elimina el piso 4
check("prune 4->2", pruneOfferedFloors([4], 2), []);
check("prune conserva válidos", pruneOfferedFloors([1, 2, 4], 2), [1, 2]);

// Opciones dinámicas
check("opciones 2 pisos", floorOptions(2).map((o) => o.label), ["Piso 1", "Piso 2"]);
check("opciones 4 pisos", floorOptions(4).length, 4);
check("opciones sin total", floorOptions(null), []);

// Visualización
check("display completa", formatFloorsDisplay(2, "full_property", []), "2 pisos · Toda la propiedad");
check("display piso 1", formatFloorsDisplay(2, "single_floor", [1]), "2 pisos · Piso 1");
check("display piso 2", formatFloorsDisplay(2, "single_floor", [2]), "2 pisos · Piso 2");
check("display varios", formatFloorsDisplay(3, "multiple_floors", [1, 2]), "3 pisos · Pisos 1 y 2");
check("display parte", formatFloorsDisplay(2, "partial", []), "2 pisos · Parte de la propiedad");

// Selector simplificado: toda la propiedad o escoger pisos (uno o varios)
check(
  "opciones del select",
  floorChoiceOptions(false).map((o) => o.label),
  ["Toda la propiedad", "Escoger pisos"]
);
check("mapeo full->toda", uiChoiceFromOffer("full_property"), "full");
check("mapeo un piso->escoger", uiChoiceFromOffer("single_floor"), "floors");
check("mapeo varios->escoger", uiChoiceFromOffer("multiple_floors"), "floors");
check("1 escogido->piso completo", offerFromSelection(1), "single_floor");
check("2 escogidos->varios", offerFromSelection(2), "multiple_floors");
check("3 escogidos->varios", offerFromSelection(3), "multiple_floors");

void FLOOR_OFFER_FULL;
void FLOOR_OFFER_SINGLE;
void FLOOR_OFFER_MULTIPLE;
void FLOOR_OFFER_PARTIAL;

if (failures > 0) {
  console.error(`${failures} fallos`);
  process.exit(1);
}
console.log("floor-offer: todo OK");
