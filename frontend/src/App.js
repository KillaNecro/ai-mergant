import React from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Products from "./pages/Products";
import ImportPage from "./pages/Import";
import BulkOps from "./pages/BulkOps";
import ExportPage from "./pages/Export";
import Settings from "./pages/Settings";
import "./App.css";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/urunler" element={<Products />} />
          <Route path="/ice-aktar" element={<ImportPage />} />
          <Route path="/toplu" element={<BulkOps />} />
          <Route path="/disa-aktar" element={<ExportPage />} />
          <Route path="/ayarlar" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
