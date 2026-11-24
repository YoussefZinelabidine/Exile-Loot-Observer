// `unknown_mod` is reserved: unknown mod lines are returned in `unrecognised`, not thrown.
export type ParseErrorCode = "unsupported_language" | "not_an_item" | "unidentified" | "unknown_mod";

/** Typed parser failure. `detail` is for logs and tests, never shown as a translation key. */
export class ParseError extends Error {
  readonly code: ParseErrorCode;
  readonly detail: string;

  constructor(code: ParseErrorCode, detail = "") {
    super(detail ? `${code}: ${detail}` : code);
    this.name = "ParseError";
    this.code = code;
    this.detail = detail;
  }
}
