import { Navigate, Route, Routes } from "react-router";
import { LinkButton } from "../../components/Button";
import { Page } from "../../components/Page";
import { EmptyState } from "../../components/States";
import { Tabs } from "../../components/Tabs";
import { AboutSection } from "./AboutSection";
import { CellProfileEditor } from "./CellProfileEditor";
import { CellProfilesSection } from "./CellProfilesSection";
import { GpuTargetsSection } from "./GpuTargetsSection";

/** #/settings and below: cell profiles (list, editor, versions), the enabled GPU targets, and about. Each section is its
 *  own address under #/settings, so a link can open the editor on one profile (docs/notes/frontend-plan.md, 9). */
export function SettingsPage() {
  return (
    <Page title="Settings" description="The cells jobs are designed for, and how this app is set up.">
      <Tabs
        label="Settings sections"
        tabs={[
          { to: "/settings/cells", label: "Cell profiles" },
          { to: "/settings/gpu", label: "GPU targets" },
          { to: "/settings/about", label: "About" },
        ]}
      />
      <Routes>
        <Route index element={<Navigate to="cells" replace />} />
        <Route path="cells" element={<CellProfilesSection />} />
        <Route path="cells/:id" element={<CellProfileEditor />} />
        <Route path="gpu" element={<GpuTargetsSection />} />
        <Route path="about" element={<AboutSection />} />
        <Route
          path="*"
          element={
            <EmptyState
              title="There's no setting at this address"
              action={
                <LinkButton variant="secondary" to="/settings/cells">
                  Back to the cell profiles
                </LinkButton>
              }
            />
          }
        />
      </Routes>
    </Page>
  );
}
