import { Route, Routes } from "react-router";
import { FingerDetailPage } from "./FingerDetailPage";
import { FingerLibraryPage } from "./FingerLibraryPage";

/** #/fingers and below: the finger library, and one finger. */
export function FingersPage() {
  return (
    <Routes>
      <Route index element={<FingerLibraryPage />} />
      <Route path=":id" element={<FingerDetailPage />} />
    </Routes>
  );
}
