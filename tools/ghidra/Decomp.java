// Decompile listed functions only, plus the strings each references.
//   tools/ghidra/run.sh Decomp.java CFILE ADDR [ADDR...]
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.data.StringDataInstance;

public class Decomp extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        DecompInterface dec = new DecompInterface(); dec.openProgram(currentProgram);
        var out = new java.io.PrintWriter(a[0]);
        for (int i = 1; i < a.length; i++) {
            Function f = getFunctionContaining(toAddr(a[i]));
            if (f == null) { out.println("---- " + a[i] + " (no function)"); continue; }
            out.println("---- " + f.getEntryPoint() + " " + f.getName());
            for (Instruction ins : currentProgram.getListing().getInstructions(f.getBody(), true))
                for (var r : ins.getReferencesFrom()) {
                    Data d = getDataAt(r.getToAddress());
                    if (d != null && d.hasStringValue()) out.println("// str " + ins.getAddress() + ": " + d.getValue());
                }
            DecompileResults r = dec.decompileFunction(f, 60, monitor);
            out.println(r.decompileCompleted() ? r.getDecompiledFunction().getC() : "(failed)");
        }
        out.close();
    }
}
