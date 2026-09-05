/**
 * Grower-facing zone name: local label if set, otherwise Rachio's zone number.
 */
export function zoneDisplayName(
  zone?: {
    display_name?: string | null;
    label?: string | null;
    zone_number?: number | null;
    id?: string;
    zone_id?: string;
  } | null,
  zoneId?: string | null,
): string | null {
  if (zone?.display_name) return zone.display_name;
  const label = zone?.label?.trim();
  if (label) return label;
  if (zone?.zone_number) return `Zone ${zone.zone_number}`;
  const id = zone?.id ?? zone?.zone_id ?? zoneId ?? null;
  if (!id) return null;
  return `Zone ${id}`;
}
