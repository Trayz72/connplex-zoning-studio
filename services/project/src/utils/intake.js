export const INTAKE_REQUIRED_FIELDS = [
  'property_name',
  'client_name',
  'client_mobile',
  'client_email',
  'google_location',
  'city',
  'state',
  'property_source',
  'floor_shop_no',
  'property_status',
  'beam_bottom_clear_height',
  'property_type'
];

export function computeIsIntakeComplete(project) {
  for (const field of INTAKE_REQUIRED_FIELDS) {
    const val = project[field];
    if (val === undefined || val === null || String(val).trim() === '') {
      return 0;
    }
  }
  return 1;
}
