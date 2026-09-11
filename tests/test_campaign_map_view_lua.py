"""Execute the shipped Lua reader against engine doubles, not native DF."""

from pathlib import Path
import shutil
import subprocess

import pytest

LUA = shutil.which("lua")
SOURCE = (Path(__file__).resolve().parents[1] / "hook/campaign_map_view_v1.lua").read_text()
PRELUDE = r"""
local captured, tile_reads, type_reads, forbidden_calls = nil, 0, 0, 0
local cells, blocks_missing = {}, false
local function cell(x,y,z)
  return cells[x..','..y..','..z] or {kind=1, hidden=false, flow_size=0, liquid_type=false}
end
require = function(name)
  assert(name == 'json')
  return {encode=function(value) captured=value; return '{}' end}
end
print = function(value) assert(value == '{}') end
df = {
  global={cur_year=30, cur_year_tick=212801, pause_state=true},
  tiletype_shape={
    FLOOR=1, WALL=2, STAIR_UP=3, STAIR_DOWN=4, STAIR_UPDOWN=5,
    RAMP=6, RAMP_TOP=7, EMPTY=8, SHRUB=9, SAPLING=10, BOULDER=11, PEBBLES=12,
  },
  tiletype_material={SOIL=0, TREE=1, FROZEN_LIQUID=2},
  tiletype={attrs={
    [1]={shape=1,material=0}, [2]={shape=2,material=0}, [3]={shape=2,material=1},
    [4]={shape=1,material=2}, [5]={shape=3,material=0}, [6]={shape=4,material=0},
    [7]={shape=5,material=0}, [8]={shape=6,material=0}, [9]={shape=8,material=0},
    [10]={shape=9,material=0}, [11]={shape=10,material=0}, [12]={shape=11,material=0},
    [13]={shape=77,material=0},
  }},
}
local function forbidden()
  forbidden_calls=forbidden_calls+1
  error('No allocation, game command or reveal is allowed')
end
dfhack = {run_command=forbidden, maps={
  getTileSize=function() return 64,48,20 end,
  getSize=forbidden, ensureTileBlock=forbidden,
  getTileBlock=function(x,y,z)
    tile_reads=tile_reads+1
    assert(x>=0 and x<64 and y>=0 and y<48 and z>=0 and z<20)
    if blocks_missing then return nil end
    local value=cell(x,y,z)
    local function grid(get)
      return setmetatable({}, {__index=function(_,xx)
        assert(xx==x%16)
        return setmetatable({}, {__index=function(_,yy)
          assert(yy==y%16)
          return get()
        end})
      end})
    end
    return {
      designation=grid(function() return value end),
      tiletype=grid(function()
        type_reads=type_reads+1
        assert(not value.hidden, 'Hidden terrain type must never be read')
        if value.unreadable then error('Injected unreadable tile') end
        return value.kind
      end),
    }
  end,
}}
"""


def run_lua(setup, arguments, assertions):
    if LUA is None:
        pytest.skip("Lua interpreter is unavailable")
    script = (
        PRELUDE
        + setup
        + "\nlocal function hook(...)\n"
        + SOURCE
        + "\nend\nhook("
        + arguments
        + ")\n"
        + "assert(forbidden_calls == 0)\n"
        + assertions
    )
    result = subprocess.run([LUA, "-"], input=script, text=True, capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr


def test_dimension_only_read_does_not_choose_a_view_or_read_tiles():
    run_lua(
        "",
        "",
        """
assert(captured.ok and not captured.active)
assert(captured.map_dimensions[1]==64 and captured.map_dimensions[3]==20)
assert(tile_reads==0 and captured.map_rows==nil)
assert(df.global.pause_state and df.global.cur_year_tick==212801)
""",
    )


def test_arbitrary_non_fort_region_and_z_are_used_exactly():
    run_lua(
        "cells['41,27,18']={kind=2,hidden=false}",
        "'40','27','18','3','2'",
        """
assert(captured.ok and captured.active)
assert(captured.map_origin[1]==40 and captured.map_origin[2]==27 and captured.map_origin[3]==18)
assert(captured.map_size[1]==3 and captured.map_size[2]==2)
assert(captured.map_rows[1]=='.#.' and captured.map_rows[2]=='...')
assert(captured.visible_tiles==6 and captured.hidden_tiles==0 and captured.scan_complete)
assert(tile_reads==6 and type_reads==6)
assert(df.global.pause_state and df.global.cur_year==30 and df.global.cur_year_tick==212801)
""",
    )


def test_hidden_tile_type_is_not_read_or_revealed():
    run_lua(
        "cells['3,4,5']={kind=999,hidden=true}",
        "'3','4','5','2','1'",
        """
assert(captured.ok and captured.map_rows[1]==' .')
assert(captured.hidden_tiles==1 and captured.visible_tiles==1 and type_reads==1)
assert(cells['3,4,5'].hidden==true and cells['3,4,5'].kind==999)
""",
    )


@pytest.mark.parametrize(
    "setup",
    [
        "blocks_missing=true",
        "cells['0,0,0']={hidden=false,unreadable=true}",
        "cells['0,0,0']={kind=999,hidden=false}",
        "cells['0,0,0']={kind=1}",  # Missing visibility is not a visible tile.
    ],
)
def test_unreadable_tile_is_blank_and_incomplete_not_empty_floor(setup):
    run_lua(
        setup,
        "'0','0','0','1','1'",
        """
assert(captured.ok and captured.map_rows[1]==' ')
assert(captured.unreadable_tiles==1 and captured.visible_tiles==0 and not captured.scan_complete)
""",
    )


@pytest.mark.parametrize(
    "arguments,error",
    [
        ("'1'", "view_requires_x_y_z_width_height"),
        ("'0','0','0','35','1'", "view_parameters_out_of_bounds"),
        ("'0','0','0','0','1'", "view_parameters_out_of_bounds"),
        ("'-1','0','0','1','1'", "view_parameters_out_of_bounds"),
        ("'1.5','0','0','1','1'", "view_parameters_out_of_bounds"),
        ("'nil','0','0','1','1'", "view_parameters_out_of_bounds"),
        ("'64','0','0','1','1'", "view_rectangle_outside_map"),
        ("'63','0','0','2','1'", "view_rectangle_outside_map"),
        ("'0','47','0','1','2'", "view_rectangle_outside_map"),
        ("'0','0','20','1','1'", "view_rectangle_outside_map"),
    ],
)
def test_bad_or_outside_requests_are_not_clamped_or_scanned(arguments, error):
    run_lua(
        "",
        arguments,
        f"""
assert(not captured.ok and captured.error=='{error}')
assert(tile_reads==0 and captured.map_origin==nil)
""",
    )


def test_full_window_is_bounded_and_final_map_edge_is_legal():
    run_lua(
        "",
        "'30','14','19','34','34'",
        """
assert(captured.ok and #captured.map_rows==34 and #captured.map_rows[1]==34)
assert(tile_reads==1156 and captured.visible_tiles==1156)
""",
    )


def test_glyphs_distinguish_terrain_and_liquids_without_occupant_claims():
    run_lua(
        """
for x=0,12 do cells[x..',0,0']={kind=x+1,hidden=false} end
cells['13,0,0']={kind=1,hidden=false,flow_size=4,liquid_type=false}
cells['14,0,0']={kind=1,hidden=false,flow_size=7,liquid_type=true}
""",
        "'0','0','0','15','1'",
        """
assert(captured.map_rows[1]=='.#Ti<>X^~,sp?wL')
assert(captured.scope=='visible_terrain_only')
assert(captured.legend:find('No units, buildings, items or pathfinding',1,true))
""",
    )


@pytest.mark.parametrize(
    "setup,error",
    [
        ("df.global.pause_state=false", "paused_calendar_unavailable"),
        ("df.global.cur_year_tick=403200", "paused_calendar_unavailable"),
        ("dfhack.maps.getTileSize=function() return 0,48,20 end", "map_dimensions_unavailable"),
        ("dfhack.maps.getTileSize=function() error('unloaded') end", "map_dimensions_unavailable"),
    ],
)
def test_unavailable_native_boundary_prevents_scanning(setup, error):
    run_lua(
        setup,
        "'0','0','0','1','1'",
        f"""
assert(not captured.ok and captured.error=='{error}' and tile_reads==0)
""",
    )
