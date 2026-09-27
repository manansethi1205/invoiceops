"use client";

import { useEffect, useRef, useState } from "react";
import Image from "next/image";
import { ChevronLeft, ChevronRight, Maximize2, Minus, Plus } from "lucide-react";
import { motion } from "motion/react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

import type { ApiSchema } from "@/lib/api/client";
import { bboxStyle } from "@/lib/evidence";

pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();

export function DocumentViewer({ documentId, contentType, evidence }: { documentId: string; contentType: string; evidence: ApiSchema<"EvidenceSpan">[] }) {
  const [pages, setPages] = useState(1);
  const [page, setPage] = useState((evidence[0]?.page ?? 0) + 1);
  const [width, setWidth] = useState(680);
  const frame = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const selected = evidence[0];
    if (!selected) return;
    const animationFrame = window.requestAnimationFrame(() => {
      setPage(selected.page + 1);
      frame.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
    return () => window.cancelAnimationFrame(animationFrame);
  }, [evidence]);
  const visiblePage = Math.min(Math.max(page, 1), pages);
  const boxes = evidence.filter((item) => item.page === visiblePage - 1);
  const changePage = (next: number) => setPage(Math.min(Math.max(next, 1), pages));
  const keyboard = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowLeft") changePage(page - 1);
    if (event.key === "ArrowRight") changePage(page + 1);
    if (event.key === "+" || event.key === "=") setWidth((current) => Math.min(current + 80, 1040));
    if (event.key === "-") setWidth((current) => Math.max(current - 80, 360));
  };
  if (contentType !== "application/pdf") return <div className="document-panel" tabIndex={0} onKeyDown={keyboard} aria-label="Invoice image viewer"><ViewerToolbar page={1} pages={1} width={width} changePage={changePage} setWidth={setWidth}/><div className="document-frame" ref={frame}><Image src={`/api/backend/v1/documents/${documentId}/content`} alt="Uploaded invoice" width={width} height={Math.round(width * 1.32)} unoptimized/>{boxes.map((item,index) => <EvidenceBox key={`${item.text}-${index}`} bbox={item.bbox} active={index===0}/>)}</div></div>;
  return <div className="document-panel" tabIndex={0} onKeyDown={keyboard} aria-label="Invoice PDF viewer"><ViewerToolbar page={visiblePage} pages={pages} width={width} changePage={changePage} setWidth={setWidth}/><Document file={`/api/backend/v1/documents/${documentId}/content`} onLoadSuccess={({numPages}) => { setPages(numPages); setPage((current) => Math.min(current, numPages)); }} loading={<p className="muted">Loading document…</p>} error={<p className="field-error">Document preview could not be loaded.</p>}><div className="document-frame" ref={frame}><Page pageNumber={visiblePage} width={width} renderTextLayer={false}/>{boxes.map((item,index) => <EvidenceBox key={`${item.text}-${index}`} bbox={item.bbox} active={index===0}/>)}</div></Document></div>;
}

function ViewerToolbar({ page, pages, width, changePage, setWidth }: { page: number; pages: number; width: number; changePage: (page: number) => void; setWidth: React.Dispatch<React.SetStateAction<number>> }) {
  return <div className="viewer-toolbar" aria-label="Document controls"><button className="icon-button" aria-label="Previous page" disabled={page <= 1} onClick={() => changePage(page - 1)}><ChevronLeft/></button><span className="mono">{page} / {pages}</span><button className="icon-button" aria-label="Next page" disabled={page >= pages} onClick={() => changePage(page + 1)}><ChevronRight/></button><span className="viewer-spacer"/><button className="icon-button" aria-label="Zoom out" onClick={() => setWidth((current) => Math.max(current - 80, 360))}><Minus/></button><span className="mono">{Math.round(width / 6.8)}%</span><button className="icon-button" aria-label="Zoom in" onClick={() => setWidth((current) => Math.min(current + 80, 1040))}><Plus/></button><button className="icon-button" aria-label="Fit width" onClick={() => setWidth(680)}><Maximize2/></button></div>;
}

function EvidenceBox({ bbox, active }: { bbox: ApiSchema<"BoundingBox">; active: boolean }) {
  return <motion.span initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: .18 }} className={`evidence-box ${active ? "active" : ""}`} style={bboxStyle(bbox)} aria-hidden="true"/>;
}

