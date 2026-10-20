-- Az addon gear ajánlójának (Gear.lua) kipróbálása a játék nélkül (lásd test_wow_addon.py).
--
--   lua gear_harness.lua <Gear.lua> <esetek.lua> <eredmények.lua>
--
-- Az esetek fájlja a Cases táblát adja meg: { { gear = <a PlanData.lua gear táblája>, ilvl =
-- <itemlevel vagy nil>, active = { <csoport> = true }, showAll = <logikai> }, ... }. Minden esetre
-- kiszámolja a látható sorokat (név, állapot, megjegyzés), és Results néven kiírja.

local gearPath, casesPath, outputPath = arg[1], arg[2], arg[3]

-- A Gear.lua betöltéskor egy eseménykezelő keretet hoz létre: ennyi elég belőle.
function CreateFrame()
	return { RegisterEvent = function() end, SetScript = function() end }
end

local ns = {}
assert(loadfile(gearPath))("WoWLeveling", ns)
local Gear = ns.Gear
assert(loadfile(casesPath))()

local out = { "Results = {\n" }
for _, case in ipairs(Cases) do
	local items = Gear.BuildItems(Gear.Groups(case.gear), case.ilvl, case.active, case.showAll)
	out[#out + 1] = "\t{\n"
	for _, item in ipairs(items) do
		out[#out + 1] = string.format("\t\t{ %q, %q, %q },\n", item.row.name, item.status or "", item.note)
	end
	out[#out + 1] = "\t},\n"
end
out[#out + 1] = "}\n"
local file = assert(io.open(outputPath, "wb"))
file:write(table.concat(out))
file:close()
