// Small text helpers for the advanced item format. Written for ELO; no code copied from other projects.

export const SECTION_SEPARATOR = "--------";

/** LF-normalise (the Windows clipboard gives CRLF) and trim trailing whitespace on every line. */
export function normalizeText(text: string): string {
  return text
    .replace(/^﻿/, "")
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((l) => l.replace(/\s+$/, ""))
    .join("\n")
    .trim();
}

/** Splits normalised text into sections of non-empty lines at `--------` separator lines. */
export function splitSections(text: string): string[][] {
  const sections: string[][] = [[]];
  for (const line of text.split("\n")) {
    if (line === SECTION_SEPARATOR) {
      sections.push([]);
    } else if (line !== "") {
      sections[sections.length - 1].push(line);
    }
  }
  return sections.filter((s) => s.length > 0);
}

export function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
