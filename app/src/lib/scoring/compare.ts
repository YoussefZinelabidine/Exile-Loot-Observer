/** Plain code-point order (ids are ASCII), identical in Python; unlike localeCompare it ignores the locale. */
export const compareIds = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);
