import { Route, Routes } from "react-router";
import { LinkButton } from "../../components/Button";
import { Page } from "../../components/Page";
import { EmptyState } from "../../components/States";
import { CellProfileEditor } from "./CellProfileEditor";
import { CellProfilesSection } from "./CellProfilesSection";

/** #/cells and below: every cell (its latest profile version), and the editor on one version at #/cells/:id, so a link
 *  can open the editor on one profile (docs/notes/frontend-plan.md, 9). */
export function CellsPage() {
  return (
    <Routes>
      <Route index element={<CellProfilesSection />} />
      <Route
        path=":id"
        element={
          <Page>
            <CellProfileEditor />
          </Page>
        }
      />
      <Route
        path="*"
        element={
          <Page title="Cells">
            <EmptyState
              title="There's no cell at this address"
              action={
                <LinkButton variant="secondary" to="/cells">
                  All cells
                </LinkButton>
              }
            />
          </Page>
        }
      />
    </Routes>
  );
}
