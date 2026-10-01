from openpilot.tools.prune_routes import main


def _drive(root, counter, cache=False):
  route = root / f"{counter:08x}--0123456789"
  (route / "0").mkdir(parents=True)
  (route / "0" / "rlog.zst").write_bytes(b"x" * 10)
  if cache:
    (route / "lat_pid_sim.npz").write_bytes(b"c")
  (root / f"fetch_{counter:x}.log").write_text("ok")
  return route


def test_keeps_newest_and_pins_and_never_touches_the_rest(tmp_path):
  drives = [_drive(tmp_path, c, cache=(c == 1)) for c in range(1, 7)]
  sim_only = tmp_path / "000000ff--aaaaaaaaaa"
  sim_only.mkdir()
  (sim_only / "lat_pid_sim.npz").write_bytes(b"c")
  (tmp_path / "out").mkdir()
  (tmp_path / "KEEP").write_text(f"{drives[1].name}  # someone: evidence\n00000003\n")

  main([str(tmp_path), "--keep", "2"])  # dry run
  assert all(d.exists() for d in drives)

  main([str(tmp_path), "--keep", "2", "--apply"])
  # drive 1 loses its logs but keeps its sim cache; 4 goes entirely; 2 and 3 pinned; 5 and 6 newest
  assert sorted(p.name for p in drives[0].iterdir()) == ["lat_pid_sim.npz"]
  assert not drives[3].exists() and not (tmp_path / "fetch_4.log").exists() and not (tmp_path / "fetch_1.log").exists()
  assert all(drives[i].exists() and (tmp_path / f"fetch_{i + 1}.log").exists() for i in (1, 2, 4, 5))
  assert sim_only.exists() and (tmp_path / "out").exists()
