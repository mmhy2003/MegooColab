package jobs

import (
	"encoding/json"
	"os"
	"regexp"
	"strings"
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

var testPNG = []byte("\x89PNG\r\n\x1a\n0123456789")

type imagesReport struct {
	Prompts []string `json:"prompts"`
	Steers  []string `json:"steers"`
	Images  []struct {
		Mime  string `json:"mime"`
		Bytes int    `json:"bytes"`
		Where string `json:"where"`
	} `json:"images"`
}

func (e *env) imagesReport() imagesReport {
	e.t.Helper()
	var r imagesReport
	b, err := os.ReadFile(e.report) // written by the time the run has finished
	if err != nil {
		e.t.Fatal(err)
	}
	if err := json.Unmarshal(b, &r); err != nil {
		e.t.Fatal(err)
	}
	return r
}

// imagesEnv serves two images and points the manager at the test server.
func imagesEnv(t *testing.T, scenario string) (*env, []protocol.RunImage) {
	e := newEnvWithCache(t, scenario, 1, t.TempDir(), func(m *Manager) {})
	e.mgr.ServerURL, e.mgr.Token = e.srv.URL(), token
	e.srv.SetImage("i1", testPNG)
	e.srv.SetImage("i2", testPNG)
	return e, []protocol.RunImage{
		{ID: "i1", Filename: "phone-ios.png", ContentType: "image/png", Size: int64(len(testPNG))},
		{ID: "i2", Filename: "phone-android.png", ContentType: "image/png", Size: int64(len(testPNG))},
	}
}

func TestPromptCarriesImageBlocks(t *testing.T) {
	t.Setenv("FAKEAGENT_IMAGES", "1")
	e, imgs := imagesEnv(t, `[{"say":"ok"}]`)
	e.startRunWith("run-i", "MEG-1", func(rs *protocol.RunStart) { rs.Images = imgs })
	if rf := e.finished("run-i"); rf.Outcome != "completed" {
		t.Fatalf("finished = %+v", rf)
	}
	got := e.imagesReport().Images
	if len(got) != 2 || got[0].Mime != "image/png" || got[0].Bytes != len(testPNG) || got[1].Where != "prompt" {
		t.Fatalf("images = %+v", got)
	}
}

var imageFile = regexp.MustCompile(`\d\. (\S+-phone-[a-z]+\.png)`)

func TestImagesBecomeFilesWhenAgentCannotTakeThem(t *testing.T) {
	e, imgs := imagesEnv(t, `[{"say":"ok"}]`)
	e.startRunWith("run-f", "MEG-1", func(rs *protocol.RunStart) { rs.Images = imgs })
	if rf := e.finished("run-f"); rf.Outcome != "completed" {
		t.Fatalf("finished = %+v", rf)
	}
	r := e.imagesReport()
	if len(r.Images) != 0 || len(r.Prompts) != 1 || !strings.Contains(r.Prompts[0], "## Image files") {
		t.Fatalf("report = %+v", r)
	}
	paths := imageFile.FindAllStringSubmatch(r.Prompts[0], -1)
	if len(paths) != 2 {
		t.Fatalf("paths in %q", r.Prompts[0])
	}
	for _, p := range paths {
		if _, err := os.Stat(p[1]); !os.IsNotExist(err) {
			t.Errorf("%s still there after the run: %v", p[1], err)
		}
	}
}

func TestRunFailsWhenAnImageCannotBeDownloaded(t *testing.T) {
	e, imgs := imagesEnv(t, `[{"say":"ok"}]`)
	imgs[1].ID = "gone"
	e.startRunWith("run-g", "MEG-1", func(rs *protocol.RunStart) { rs.Images = imgs })
	rf := e.finished("run-g")
	if rf.Outcome != "failed" || rf.Error == nil || *rf.Error != "image_download_failed" {
		t.Fatalf("finished = %+v", rf)
	}
	if !strings.Contains(e.runLog("run-g"), "could not download image phone-android.png") {
		t.Errorf("log = %q", e.runLog("run-g"))
	}
}

func TestSteerCarriesImages(t *testing.T) {
	t.Setenv("FAKEAGENT_IMAGES", "1")
	e, imgs := imagesEnv(t, steerScenario)
	e.startRun("run-s", "MEG-1", "workspace")
	e.waitUpdate("run-s")
	if err := e.srv.Send(protocol.RunSteer{Type: protocol.TypeRunSteer, RunID: "run-s", MessageID: "m1", Text: steerText,
		Images: imgs[:1]}); err != nil {
		t.Fatal(err)
	}
	if r := e.steerResult("m1"); r.Outcome != protocol.SteerInjected {
		t.Fatalf("result = %+v", r)
	}
	e.finished("run-s")
	got := e.imagesReport().Images
	if len(got) != 1 || got[0].Where != "steer" {
		t.Fatalf("images = %+v", got)
	}
}
