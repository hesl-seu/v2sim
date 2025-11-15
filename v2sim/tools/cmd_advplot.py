from v2sim import AdvancedPlot, Lang
import sys

def main():
    plt = AdvancedPlot()
    if len(sys.argv) > 1:
        with open(sys.argv[1], "r") as f:
            command = f.readlines()
            plt.configure(command)
    else:
        print(Lang.ADV_PLOT_TITLE)
        while True:
            print("> ", end="")
            ln = input()
            try:
                if not plt.configure(ln):
                    break
            except Exception as e:
                print(e)
                continue


if __name__ == "__main__":
    main()
