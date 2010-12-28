(* taxtastic v0.1. Copyright (C) 2009-2010  Frederick A Matsen. 
 * This file is part of taxtastic. Taxtastic is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. Taxtastic is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details. You should have received a copy of the GNU General Public License along with taxtastic.  If not, see <http://www.gnu.org/licenses/>.  *)

open Fam_batteries
open MapsSets

let out_prefix = ref ""
let cutoff = ref 0.
let names_only = ref false

let parse_args () = 
  let files  = ref [] in
  let args = 
   [
     "-o", Arg.Set_string out_prefix,
     "Set the output prefix. Required if there are two or more input files.";
     "--cutoff", Arg.Set_float cutoff,
     "Specify the maximum branch length to be trimmed (required).";
     "--names-only", Arg.Set names_only,
     "Only split out a list of names, rather than names and PD decrease."
   ]
  in
  let usage = "trimtre trims the tree.\n"
  and anon_arg arg = files := arg :: !files in
  Arg.parse args anon_arg usage;
  if !cutoff <= 0. then
    failwith "Please specify a positive cutoff value.";
  List.rev !files

(* for out_fname options *)
let ch_of_fname = function
  | "" -> stdout
  | s -> open_out s

let wrap_output fname f = 
  let ch = ch_of_fname fname in
  f ch;
  if ch <> stdout then close_out ch

let () =
  if not !Sys.interactive then begin
    List.iter
      (fun fname ->
        let gt = Newick.of_file fname in
        let pt = Ptree.of_gtree gt 
        and get_name id = (IntMap.find id gt.Gtree.bark_map)#get_name 
        in
        let line_of_result = 
          if !names_only then (fun (id,_,_) -> [get_name id])
          else (fun (id,bl,_) -> [get_name id; string_of_float bl])
        in
        wrap_output (!out_prefix)
          (fun ch ->
            Csv.save_out ch
              (List.map line_of_result (Pd.until_stopping (!cutoff) pt))))
      (parse_args ())
  end

