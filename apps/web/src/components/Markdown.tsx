import { Fragment, type ReactNode } from "react";

// A deliberately small markdown renderer. Everything is emitted as React text
// nodes or allow-listed elements; raw HTML in the source is shown as text.

type Block =
  | { kind: "heading"; level: 2 | 3 | 4; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "code"; text: string }
  | { kind: "quote"; text: string };

const HEADING = /^(#{1,4})\s+(.*)$/;
const UNORDERED = /^\s*[-*]\s+(.*)$/;
const ORDERED = /^\s*\d+[.)]\s+(.*)$/;
const FENCE = /^```/;

export function parseBlocks(source: string): Block[] {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.trim() === "") {
      i += 1;
      continue;
    }

    if (FENCE.test(line.trim())) {
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !FENCE.test(lines[i].trim())) {
        body.push(lines[i]);
        i += 1;
      }
      i += 1; // closing fence (or end of input)
      blocks.push({ kind: "code", text: body.join("\n") });
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      const depth = heading[1].length;
      const level = depth <= 2 ? 2 : depth === 3 ? 3 : 4;
      blocks.push({ kind: "heading", level, text: heading[2].trim() });
      i += 1;
      continue;
    }

    if (line.trim().startsWith(">")) {
      const body: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith(">")) {
        body.push(lines[i].trim().replace(/^>\s?/, ""));
        i += 1;
      }
      blocks.push({ kind: "quote", text: body.join(" ") });
      continue;
    }

    const bullet = UNORDERED.exec(line);
    const number = ORDERED.exec(line);
    if (bullet || number) {
      const ordered = !bullet;
      const pattern = ordered ? ORDERED : UNORDERED;
      const items: string[] = [];
      while (i < lines.length) {
        const match = pattern.exec(lines[i]);
        if (!match) break;
        items.push(match[1].trim());
        i += 1;
      }
      blocks.push({ kind: "list", ordered, items });
      continue;
    }

    const body: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !FENCE.test(lines[i].trim()) &&
      !HEADING.test(lines[i]) &&
      !UNORDERED.test(lines[i]) &&
      !ORDERED.test(lines[i])
    ) {
      body.push(lines[i].trim());
      i += 1;
    }
    blocks.push({ kind: "paragraph", text: body.join(" ") });
  }

  return blocks;
}

const INLINE = /(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`|\[[^\]\n]+\]\([^)\s]+\))/;

function isSafeHref(href: string): boolean {
  return /^https?:\/\//i.test(href);
}

export function renderInline(text: string): ReactNode[] {
  return text.split(INLINE).map((part, index) => {
    if (part === "") return null;
    const key = `i${index}`;

    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return (
        <code key={key} className="md-code">
          {part.slice(1, -1)}
        </code>
      );
    }
    if (part.length > 2 && part.startsWith("*") && part.endsWith("*") && !part.startsWith("**")) {
      return <em key={key}>{part.slice(1, -1)}</em>;
    }
    const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(part);
    if (link) {
      if (!isSafeHref(link[2])) return <Fragment key={key}>{link[1]}</Fragment>;
      return (
        <a key={key} href={link[2]} target="_blank" rel="noopener noreferrer">
          {link[1]}
        </a>
      );
    }
    return <Fragment key={key}>{part}</Fragment>;
  });
}

export function Markdown({ source }: { source: string }) {
  const blocks = parseBlocks(source);
  return (
    <div className="md">
      {blocks.map((block, index) => {
        const key = `b${index}`;
        switch (block.kind) {
          case "heading":
            if (block.level === 2) return <h2 key={key}>{renderInline(block.text)}</h2>;
            if (block.level === 3) return <h3 key={key}>{renderInline(block.text)}</h3>;
            return <h4 key={key}>{renderInline(block.text)}</h4>;
          case "paragraph":
            return <p key={key}>{renderInline(block.text)}</p>;
          case "quote":
            return <blockquote key={key}>{renderInline(block.text)}</blockquote>;
          case "code":
            return (
              <pre key={key} className="md-pre">
                <code>{block.text}</code>
              </pre>
            );
          case "list": {
            const items = block.items.map((item, itemIndex) => (
              <li key={`${key}-${itemIndex}`}>{renderInline(item)}</li>
            ));
            return block.ordered ? (
              <ol key={key}>{items}</ol>
            ) : (
              <ul key={key}>{items}</ul>
            );
          }
        }
      })}
    </div>
  );
}
