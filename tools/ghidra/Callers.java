// Callers tree (and optional decompile) for addresses in the analysed Napoleon.exe project (work/ghidra/ntw).
//   tools/ghidra/run.sh Callers.java DEPTH CFILE|- ADDR [ADDR...]      (VA, e.g. 0x10DBDD0)
// Prints, per address: its function, then callers up to DEPTH levels (indented), each line "VA name [n callers]";
// with CFILE (a path) the C of each target function and its direct callers is written there.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import java.util.*;

public class Callers extends GhidraScript {
    DecompInterface dec;
    java.io.PrintWriter out;

    Set<Function> callers(Function f) {
        Set<Function> out = new TreeSet<>(Comparator.comparing(Function::getEntryPoint));
        for (var r : getReferencesTo(f.getEntryPoint())) {
            Function c = getFunctionContaining(r.getFromAddress());
            if (c != null && r.getReferenceType().isCall() || c != null && r.getReferenceType().isJump()) out.add(c);
        }
        return out;
    }

    void tree(Function f, int depth, int max, Set<Function> seen) {
        Set<Function> cs = callers(f);
        println("  ".repeat(depth) + f.getEntryPoint() + " " + f.getName() + " [" + cs.size() + " callers]");
        if (depth >= max || !seen.add(f)) return;
        for (Function c : cs) tree(c, depth + 1, max, seen);
    }

    void decompile(Function f) {
        DecompileResults r = dec.decompileFunction(f, 60, monitor);
        out.println("---- " + f.getEntryPoint() + " " + f.getName());
        out.println(r.decompileCompleted() ? r.getDecompiledFunction().getC() : "(decompile failed: " + r.getErrorMessage() + ")");
    }

    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        int max = Integer.parseInt(a[0]);
        boolean dc = !a[1].equals("-");
        if (dc) { dec = new DecompInterface(); dec.openProgram(currentProgram); out = new java.io.PrintWriter(a[1]); }
        for (int i = 2; i < a.length; i++) {
            Address ad = toAddr(a[i]);
            Function f = getFunctionContaining(ad);
            println("==== " + a[i] + (f == null ? " (no function)" : ""));
            if (f == null) continue;
            tree(f, 0, max, new HashSet<>());
            if (dc) { decompile(f); for (Function c : callers(f)) decompile(c); }
        }
        if (dc) out.close();
    }
}
