import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import {
  X, Wand2, RotateCcw, Save, Sparkles, AlertCircle, CheckCircle2,
  Info, AlertTriangle, XCircle, History, ClipboardCheck, ThumbsDown, RefreshCw,
} from "lucide-react";
import { toast } from "sonner";

const STATUS_LABELS = {
  imported: "İçe Aktarıldı",
  needs_attention: "Dikkat Gerekiyor",
  ready_for_ai: "AI İçin Hazır",
  awaiting_review: "İnceleme Bekliyor",
  approved: "Onaylandı",
  ready_to_publish: "Yayına Hazır",
};

const SEV_ICON = { critical: XCircle, warning: AlertTriangle, info: Info };
const SEV_TONE = {
  critical: "border-red-200 bg-red-50 text-red-700",
  warning: "border-amber-200 bg-amber-50 text-amber-700",
  info: "border-slate-200 bg-slate-50 text-slate-600",
};

const Tab = ({ id, active, children, onClick, testid }) => (
  <button
    data-testid={testid}
    onClick={() => onClick(id)}
    className={
      "px-4 py-2 text-sm font-medium border-b-2 transition-colors " +
      (active === id
        ? "border-blue-600 text-[#0A1128]"
        : "border-transparent text-slate-500 hover:text-[#0A1128]")
    }
  >
    {children}
  </button>
);

const ProductEditor = ({ productId, onClose, onSaved }) => {
  const [p, setP] = useState(null);
  const [suggestion, setSuggestion] = useState(null);
  const [issues, setIssues] = useState([]);
  const [revisions, setRevisions] = useState([]);
  const [tab, setTab] = useState("original");
  const [busy, setBusy] = useState("");
  const [loadError, setLoadError] = useState(null);

  const reload = async () => {
    setLoadError(null);
    try {
      const [pr, sr, ir, rr] = await Promise.all([
        api.get(`/products/${productId}`),
        api.get(`/products/${productId}/suggestion`),
        api.get(`/products/${productId}/issues`),
        api.get(`/products/${productId}/revisions`),
      ]);
      setP(pr.data);
      setSuggestion(sr.data);
      setIssues(ir.data);
      setRevisions(rr.data);
    } catch (e) {
      setLoadError(e?.response?.data?.detail || "Ürün yüklenemedi");
    }
  };

  useEffect(() => { reload(); /* eslint-disable-next-line */ }, [productId]);

  const run = async (key, fn, successMsg, refresh = true) => {
    if (busy) return;
    setBusy(key);
    try {
      const res = await fn();
      if (successMsg) toast.success(successMsg);
      if (refresh) await reload();
      return res;
    } catch (e) {
      toast.error(e?.response?.data?.detail || "İşlem başarısız");
    } finally { setBusy(""); }
  };

  const analyze = () => run("analyze", () => api.post(`/products/${productId}/analyze`), "Analiz tamamlandı");
  const suggest = () => run("suggest", () => api.post(`/products/${productId}/suggest`), "AI önerisi hazırlandı");
  const saveSuggestion = () => {
    if (!suggestion) return;
    return run("save", () => api.patch(`/products/${productId}/suggestion`, {
      suggested_name: suggestion.suggested_name,
      suggested_description: suggestion.suggested_description,
      suggested_category: suggestion.suggested_category,
      suggested_seo_title: suggestion.suggested_seo_title,
      suggested_meta_description: suggestion.suggested_meta_description,
      suggested_tags: suggestion.suggested_tags,
    }), "Öneri kaydedildi");
  };
  const approve = async () => {
    if (!window.confirm("Bu öneriyi onaylamak istiyor musunuz?")) return;
    const res = await run("approve", () => api.post(`/products/${productId}/suggestion/approve`), null);
    if (res?.data) {
      if (res.data.ready_to_publish) toast.success("Yayına hazır olarak işaretlendi");
      else toast.warning(`Onaylandı ama yayına hazır değil: ${(res.data.blocking_reasons || []).join(", ")}`);
    }
  };
  const reject = async () => {
    if (!window.confirm("Bu öneriyi reddetmek istiyor musunuz? Geçmişte kalacak ama aktif olmayacak.")) return;
    return run("reject", () => api.post(`/products/${productId}/suggestion/reject`), "Öneri reddedildi");
  };
  const revert = async (revId) => {
    if (!window.confirm("Seçilen revizyona dönmek istiyor musunuz? Orijinal ürün verisi değişmez.")) return;
    return run(`revert-${revId}`, () => api.post(`/products/${productId}/revisions/${revId}/revert`), "Revizyondan geri yüklendi");
  };

  const setSug = (k, v) => setSuggestion({ ...(suggestion || {}), [k]: v });

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/40 flex items-start justify-center p-4 overflow-y-auto" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}
        className="bg-white rounded-md border border-slate-200 shadow-lg w-full max-w-6xl my-8"
        data-testid="product-editor">
        <div className="h-14 flex items-center justify-between px-6 border-b border-slate-200">
          <div>
            <div className="text-xs text-slate-500 uppercase tracking-widest">Ürün Editörü</div>
            <div className="font-semibold text-[#0A1128] tracking-tight flex items-center gap-3">
              {p ? (suggestion?.suggested_name || p.name) : "Yükleniyor..."}
              {p && (
                <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-medium text-slate-700">
                  {STATUS_LABELS[p.workflow_status] || p.workflow_status}
                </span>
              )}
              {p?.quality_score != null && (
                <span className="text-xs font-medium text-slate-500">Kalite: {p.quality_score}</span>
              )}
            </div>
          </div>
          <button data-testid="editor-close" onClick={onClose} className="text-slate-500 hover:text-[#0A1128]"><X size={18} /></button>
        </div>

        {loadError && <div className="p-6 text-red-700 text-sm"><AlertCircle size={16} className="inline mr-2" />{loadError}</div>}

        {p && (
          <>
            <div className="px-6 flex items-center gap-1 border-b border-slate-200">
              <Tab id="original" active={tab} onClick={setTab} testid="tab-original">Orijinal Veri</Tab>
              <Tab id="ai" active={tab} onClick={setTab} testid="tab-ai">AI Önerisi</Tab>
              <Tab id="quality" active={tab} onClick={setTab} testid="tab-quality">Kalite Analizi <span className="ml-1 text-xs text-slate-500">({issues.length})</span></Tab>
              <Tab id="history" active={tab} onClick={setTab} testid="tab-history">Revizyon Geçmişi</Tab>
              <div className="ml-auto flex items-center gap-2 py-2">
                <button data-testid="analyze-btn" disabled={!!busy} onClick={analyze}
                  className="inline-flex items-center gap-1 bg-white border border-slate-200 hover:bg-slate-50 rounded-md px-3 py-1.5 text-xs font-medium text-[#0A1128] disabled:opacity-60">
                  <ClipboardCheck size={12} /> {busy === "analyze" ? "..." : "Kaliteyi Analiz Et"}
                </button>
                <button data-testid="suggest-btn" disabled={!!busy} onClick={suggest}
                  className="inline-flex items-center gap-1 bg-blue-600 hover:bg-blue-700 text-white rounded-md px-3 py-1.5 text-xs font-medium disabled:opacity-60">
                  <Sparkles size={12} /> {busy === "suggest" ? "..." : "AI Önerisi Oluştur"}
                </button>
              </div>
            </div>

            <div className="p-6">
              {tab === "original" && (
                <div data-testid="panel-original" className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <ReadOnly label="Ürün Adı" value={p.name} />
                  <ReadOnly label="SKU" value={p.sku} />
                  <ReadOnly label="Kategori" value={p.category} />
                  <ReadOnly label="Fiyat" value={p.price != null ? `₺${Number(p.price).toLocaleString("tr-TR", { minimumFractionDigits: 2 })}` : "-"} />
                  <ReadOnly label="Stok" value={p.stock ?? 0} />
                  <ReadOnly label="Görsel URL" value={p.image_url || "-"} />
                  <ReadOnly label="Ürün URL" value={p.product_url || "-"} />
                  <div className="md:col-span-2">
                    <ReadOnly label="Açıklama" value={p.description || "(boş)"} multiline />
                  </div>
                </div>
              )}

              {tab === "ai" && (
                <div data-testid="panel-ai" className="space-y-6">
                  {!suggestion && (
                    <div className="border border-dashed border-slate-200 rounded-md p-6 text-center text-slate-500 text-sm">
                      Henüz bir AI önerisi yok. "AI Önerisi Oluştur" butonuna basın.
                    </div>
                  )}
                  {suggestion && (
                    <>
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs">
                          Sağlayıcı: {suggestion.provider}{suggestion.model ? ` · ${suggestion.model}` : ""}
                        </span>
                        <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs">
                          Durum: {suggestion.suggestion_status}
                        </span>
                        <div className="ml-auto flex gap-2">
                          <button data-testid="save-suggestion-btn" onClick={saveSuggestion} disabled={!!busy || suggestion.suggestion_status !== "draft"}
                            className="inline-flex items-center gap-1 bg-white border border-slate-200 hover:bg-slate-50 text-[#0A1128] rounded-md px-3 py-1.5 text-xs font-medium disabled:opacity-60">
                            <Save size={12} /> Öneriyi Kaydet
                          </button>
                          <button data-testid="approve-btn" onClick={approve} disabled={!!busy || suggestion.suggestion_status !== "draft"}
                            className="inline-flex items-center gap-1 bg-emerald-600 hover:bg-emerald-700 text-white rounded-md px-3 py-1.5 text-xs font-medium disabled:opacity-60">
                            <CheckCircle2 size={12} /> Onayla
                          </button>
                          <button data-testid="reject-btn" onClick={reject} disabled={!!busy || suggestion.suggestion_status !== "draft"}
                            className="inline-flex items-center gap-1 bg-white border border-red-200 hover:bg-red-50 text-red-700 rounded-md px-3 py-1.5 text-xs font-medium disabled:opacity-60">
                            <ThumbsDown size={12} /> Reddet
                          </button>
                        </div>
                      </div>
                      <SideBySide label="Başlık" original={p.name}
                        value={suggestion.suggested_name || ""} onChange={(v) => setSug("suggested_name", v)}
                        disabled={suggestion.suggestion_status !== "draft"} testid="sug-name" />
                      <SideBySide label="Açıklama" original={p.description || "(boş)"}
                        value={suggestion.suggested_description || ""} onChange={(v) => setSug("suggested_description", v)}
                        disabled={suggestion.suggestion_status !== "draft"} multiline testid="sug-desc" />
                      <SideBySide label="Kategori" original={p.category || "(boş)"}
                        value={suggestion.suggested_category || ""} onChange={(v) => setSug("suggested_category", v)}
                        disabled={suggestion.suggestion_status !== "draft"} testid="sug-cat" />
                      <SideBySide label="SEO Başlık" original="—"
                        value={suggestion.suggested_seo_title || ""} onChange={(v) => setSug("suggested_seo_title", v)}
                        disabled={suggestion.suggestion_status !== "draft"} hint="Maks 60 karakter" testid="sug-seo" />
                      <SideBySide label="Meta Açıklama" original="—"
                        value={suggestion.suggested_meta_description || ""} onChange={(v) => setSug("suggested_meta_description", v)}
                        disabled={suggestion.suggestion_status !== "draft"} multiline hint="Maks 155 karakter" testid="sug-meta" />
                      <div>
                        <label className="text-xs text-slate-500 uppercase tracking-widest">Etiketler (virgülle ayrılmış)</label>
                        <input data-testid="sug-tags" value={(suggestion.suggested_tags || []).join(", ")}
                          onChange={(e) => setSug("suggested_tags", e.target.value.split(",").map(s => s.trim()).filter(Boolean))}
                          disabled={suggestion.suggestion_status !== "draft"}
                          className="mt-1 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm disabled:bg-slate-50" />
                      </div>
                    </>
                  )}
                </div>
              )}

              {tab === "quality" && (
                <div data-testid="panel-quality" className="space-y-3">
                  {issues.length === 0 && (
                    <div className="border border-slate-200 rounded-md p-6 text-center text-slate-500 text-sm">
                      Aktif sorun yok. Henüz analiz yapılmadıysa "Kaliteyi Analiz Et" butonuna basın.
                    </div>
                  )}
                  {issues.map((i) => {
                    const Icon = SEV_ICON[i.severity] || Info;
                    return (
                      <div key={i.id} className={`border rounded-md p-3 text-sm ${SEV_TONE[i.severity]}`} data-testid={`issue-${i.issue_code}`}>
                        <div className="flex items-start gap-2">
                          <Icon size={16} className="mt-0.5 flex-shrink-0" />
                          <div className="flex-1">
                            <div className="font-medium">
                              {i.message}
                              <span className="ml-2 text-xs text-slate-500">[{i.issue_code} · {i.field_name || "-"}]</span>
                            </div>
                            {i.recommendation && <div className="mt-1 text-xs opacity-90">Öneri: {i.recommendation}</div>}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {tab === "history" && (
                <div data-testid="panel-history" className="space-y-2">
                  {revisions.length === 0 && (
                    <div className="border border-slate-200 rounded-md p-6 text-center text-slate-500 text-sm">Henüz revizyon yok.</div>
                  )}
                  {revisions.map((r) => (
                    <div key={r.id} className="border border-slate-200 rounded-md p-3 flex items-start gap-3 text-sm" data-testid={`rev-${r.action_type}`}>
                      <History size={14} className="mt-0.5 text-slate-400" />
                      <div className="flex-1">
                        <div className="font-medium text-[#0A1128]">
                          {r.action_type} <span className="text-xs text-slate-500">· {r.source} · {new Date(r.created_at).toLocaleString("tr-TR")}</span>
                        </div>
                        {r.after_snapshot?.suggested_name && (
                          <div className="text-xs text-slate-600 mt-1 line-clamp-1">→ {r.after_snapshot.suggested_name}</div>
                        )}
                      </div>
                      {(r.action_type === "suggest" || r.action_type === "approve" || r.action_type === "edit") && (
                        <button onClick={() => revert(r.id)} disabled={!!busy} data-testid={`revert-${r.id}`}
                          className="inline-flex items-center gap-1 bg-white border border-slate-200 hover:bg-slate-50 rounded-md px-2 py-1 text-xs font-medium text-[#0A1128] disabled:opacity-60">
                          <RefreshCw size={12} /> Önceki Sürüme Dön
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="h-14 flex items-center justify-end gap-2 px-6 border-t border-slate-200 bg-slate-50/50">
              <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-[#0A1128]">Kapat</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

const ReadOnly = ({ label, value, multiline }) => (
  <div className="space-y-1">
    <div className="text-xs text-slate-500 uppercase tracking-widest">{label}</div>
    <div className={"rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 " + (multiline ? "min-h-[120px] whitespace-pre-wrap" : "")}>
      {value || "-"}
    </div>
  </div>
);

const SideBySide = ({ label, original, value, onChange, disabled, multiline, hint, testid }) => (
  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
    <div className="space-y-1">
      <div className="text-xs text-slate-500 uppercase tracking-widest">Orijinal · {label}</div>
      <div className={"rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 " + (multiline ? "min-h-[120px] whitespace-pre-wrap" : "")}>
        {original || "-"}
      </div>
    </div>
    <div className="space-y-1">
      <div className="text-xs text-slate-500 uppercase tracking-widest">Öneri · {label} {hint && <span className="text-slate-400 lowercase font-normal">({hint})</span>}</div>
      {multiline ? (
        <textarea data-testid={testid} value={value} onChange={(e) => onChange(e.target.value)} rows={5} disabled={disabled}
          className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:bg-slate-50" />
      ) : (
        <input data-testid={testid} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}
          className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:bg-slate-50" />
      )}
    </div>
  </div>
);

export default ProductEditor;
