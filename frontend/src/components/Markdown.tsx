import DOMPurify from "dompurify";
import { marked } from "marked";
import { useMemo } from "react";

export default function Markdown({ text, className }: { text: string; className?: string }) {
  const html = useMemo(() => DOMPurify.sanitize(marked.parse(text, { async: false })), [text]);
  return <div className={className} dangerouslySetInnerHTML={{ __html: html }} />;
}
