import { Route, Routes } from "react-router";
import { PartDetailPage } from "./PartDetailPage";
import { PartsLibraryPage } from "./PartsLibraryPage";

/** #/parts and below: the parts library, and one part. */
export function PartsPage() {
  return (
    <Routes>
      <Route index element={<PartsLibraryPage />} />
      <Route path=":id" element={<PartDetailPage />} />
    </Routes>
  );
}
